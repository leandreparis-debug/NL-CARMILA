"""Tests de l'étape 9 : e-mail HTML pour Gmail, paquet Apps Script, pages d'export."""

from __future__ import annotations

import base64
import io
import json
import re
import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime
from email import message_from_bytes, policy
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from news_franchise.config import ConfigError, Settings, load_settings
from news_franchise.models import (
    Article,
    Franchisee,
    Meeting,
    Newsletter,
    Opening,
    OpeningPhoto,
)
from news_franchise.newsletter import email as email_module
from news_franchise.newsletter import shapes
from news_franchise.newsletter.email import (
    GMAIL_CLIP_BYTES,
    MAIN_PHOTO_SIZE,
    PACKAGE_FORMAT,
    build_email,
    package_json,
    write_email_export,
)
from news_franchise.newsletter.view import EmptyNewsletterError
from news_franchise.repositories import articles, franchisees, meetings, openings
from news_franchise.tools import demo
from tests.helpers import post_form

PROJECT = Path(__file__).resolve().parent.parent


def _html(response: object) -> str:
    return response.get_data(as_text=True)  # type: ignore[attr-defined]


@pytest.fixture
def demo_settings(settings: Settings, app: Flask) -> Settings:
    assert demo.main([], settings=settings, out=lambda _: None) == 0
    return settings


def _email(app: Flask, conn: sqlite3.Connection, settings: Settings, month: str = "2000-01"):
    with app.app_context():
        return build_email(conn, month, settings)


# --------------------------------------------------------------------------- e-mail


def test_demo_email_respects_gmail_rules(
    app: Flask, conn: sqlite3.Connection, demo_settings: Settings
) -> None:
    export = _email(app, conn, demo_settings)
    html = export.html
    assert export.subject == "News Franchise — Janvier 2000"
    # Gmail : pas de SVG, pas de feuille de style ni de mise en page flex/grid, ni script.
    lowered = html.lower()
    for forbidden in ("<svg", "<style", "display:flex", "display:grid", "<script", "position:"):
        assert forbidden not in lowered, forbidden
    # Sous la limite de troncature de Gmail, sans avertissement.
    assert export.html_size < GMAIL_CLIP_BYTES
    assert export.warnings == ()
    # Largeur fixe de 600 px.
    assert 'width="600"' in html


def test_every_image_is_attached_and_used(
    app: Flask, conn: sqlite3.Connection, demo_settings: Settings
) -> None:
    export = _email(app, conn, demo_settings)
    referenced = set(re.findall(r'src="cid:([^"]+)"', export.html))
    attached = {image.cid for image in export.images}
    assert referenced == attached
    assert not re.search(r'src="(?!cid:)', export.html)  # aucune image hébergée ailleurs
    for image in export.images:
        with Image.open(io.BytesIO(image.data)) as opened:
            assert opened.format == ("PNG" if image.mime_type == "image/png" else "JPEG")
    photos = [image for image in export.images if image.cid.startswith("nf-photo")]
    assert len(photos) == 3  # 2 photos principales + 1 vignette
    with Image.open(io.BytesIO(photos[0].data)) as main_photo:
        assert main_photo.size == MAIN_PHOTO_SIZE


def test_email_links_and_escaping(
    app: Flask, conn: sqlite3.Connection, demo_settings: Settings
) -> None:
    export = _email(app, conn, demo_settings)
    links = set(re.findall(r'href="([^"]+)"', export.html))
    assert links  # liens des articles et des plans, tous réels (http/https)
    assert all(link.startswith(("https://", "http://")) for link in links)
    assert "https://example.com/demo/plans" in links
    assert "&lt;script&gt;alert(" in export.html
    assert "<script>alert" not in export.html


def _fill(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    for n, selected in ((1, True), (2, False)):
        articles.add(
            conn,
            Article(
                newsletter_id=newsletter.id,
                rubric=1,
                title=f"Titre {n}",
                source_name="Source test",
                url=f"https://example.com/a{n}",
                published_at=datetime(2026, 10, n, 8, tzinfo=UTC),
                selected=selected,
                is_opportunity=n == 1,
            ),
        )
    franchisees.add(
        conn,
        Franchisee(
            newsletter_id=newsletter.id,
            name="Alice Test",
            source_name="Source test",
            source_url="https://example.com/a1",
            validated=True,
        ),
    )
    meetings.add(conn, Meeting(newsletter_id=newsletter.id, brand_name="Pokawa"))


def test_email_keeps_only_retained_and_validated(
    app: Flask, conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    _fill(conn, newsletter)
    export = _email(app, conn, settings, "2026-10")
    assert "Titre 1" in export.html and "Titre 2" not in export.html
    assert "Alice Test" in export.html
    assert "point de vente" not in export.html  # nombre inconnu : rien d'affiché
    # Version texte : titres, liens, repère opportunité.
    assert "Titre 1" in export.text and "https://example.com/a1" in export.text
    assert "Opportunité emplacements" in export.text
    assert "Titre 2" not in export.text


def test_empty_newsletter_cannot_be_exported(
    app: Flask, conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    with pytest.raises(EmptyNewsletterError):
        _email(app, conn, settings, "2026-10")


def test_big_html_gives_a_warning(
    app: Flask,
    conn: sqlite3.Connection,
    demo_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(email_module, "GMAIL_CLIP_MARGIN", 1000)
    export = _email(app, conn, demo_settings)
    assert len(export.warnings) == 1 and "102 Ko" in export.warnings[0]


def test_photo_is_cropped_not_distorted(
    app: Flask, conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    assert newsletter.id is not None
    folder = settings.photos_dir / "2026-10"
    folder.mkdir(parents=True)
    Image.new("RGB", (1600, 600), (10, 120, 200)).save(folder / "large.jpg")
    opening = openings.add(
        conn,
        Opening(
            newsletter_id=newsletter.id,
            brand_name="Wycon",
            location="Lyon",
            opening_date=date(2026, 10, 2),
        ),
    )
    assert opening.id is not None
    openings.add_photo(conn, OpeningPhoto(opening_id=opening.id, file_name="2026-10/large.jpg"))
    export = _email(app, conn, settings, "2026-10")
    photo = next(image for image in export.images if image.cid == "nf-photo-1")
    with Image.open(io.BytesIO(photo.data)) as opened:
        assert opened.size == MAIN_PHOTO_SIZE


# --------------------------------------------------------------------------- paquet


def test_package_round_trip(app: Flask, conn: sqlite3.Connection, demo_settings: Settings) -> None:
    export = _email(app, conn, demo_settings)
    data = json.loads(package_json(export, datetime(2000, 2, 1, 9, tzinfo=UTC)))
    assert data["format"] == PACKAGE_FORMAT
    assert data["month"] == "2000-01" and data["subject"] == export.subject
    assert data["htmlBody"] == export.html and data["textBody"] == export.text
    assert data["createdAt"] == "2000-02-01T09:00:00+00:00"
    for packed, image in zip(data["images"], export.images, strict=True):
        assert packed["cid"] == image.cid and packed["mimeType"] == image.mime_type
        assert base64.b64decode(packed["data"]) == image.data


def test_write_export_replaces_previous_and_copies_to_drive(
    app: Flask, conn: sqlite3.Connection, demo_settings: Settings, tmp_path: Path
) -> None:
    export = _email(app, conn, demo_settings)
    files = write_email_export(export, demo_settings)
    assert files.html.is_file() and files.package.is_file() and files.drive_copy is None
    assert (files.folder / "news-franchise-2000-01.eml").is_file()
    stale = files.folder / "images" / "ancienne.png"
    stale.write_bytes(b"x")
    # La version navigateur appelle les images voisines, pas des cid.
    browser = files.html.read_text(encoding="utf-8")
    assert "cid:" not in browser and 'src="images/nf-logo-blanc.png"' in browser

    drive = tmp_path / "drive"
    drive.mkdir()
    files = write_email_export(export, replace(demo_settings, drive_dir=drive))
    assert not stale.exists()
    assert files.drive_copy == drive / "news-franchise-2000-01.json"
    assert files.drive_copy.read_text(encoding="utf-8") == files.package.read_text(encoding="utf-8")


def test_drive_dir_setting(tmp_path: Path) -> None:
    env = {"NF_DATA_DIR": str(tmp_path / "data"), "NF_OPEN_BROWSER": "false"}
    assert load_settings(env).drive_dir is None
    with pytest.raises(ConfigError, match="NF_DRIVE_DIR"):
        load_settings({**env, "NF_DRIVE_DIR": str(tmp_path / "absent")})
    (tmp_path / "drive").mkdir()
    assert (
        load_settings({**env, "NF_DRIVE_DIR": str(tmp_path / "drive")}).drive_dir
        == (tmp_path / "drive").resolve()
    )


def test_apps_script_matches_package_format() -> None:
    script = (PROJECT / "apps_script" / "brouillon_gmail.gs").read_text(encoding="utf-8")
    assert f"const FORMAT_PAQUET = '{PACKAGE_FORMAT}';" in script
    # Brouillon créé à partir du message MIME complet (API Gmail), jamais envoyé.
    assert "Gmail.Users.Drafts.create({ message: { raw: raw } }, 'me')" in script
    # Bouton « Imprimer » : PDF déposé dans Drive, partagé, lien remplacé dans le message.
    assert "deposerPdf_(dossier, paquet.printPdf)" in script
    assert "remplacerLien_(raw, paquet.printLinkToken, lienPdf)" in script
    assert "const PARTAGE_PDF = 'DOMAINE';" in script
    assert ".send(" not in script and "sendEmail" not in script
    manifest = json.loads((PROJECT / "apps_script" / "appsscript.json").read_text("utf-8"))
    services = manifest["dependencies"]["enabledAdvancedServices"]
    assert {"userSymbol": "Gmail", "serviceId": "gmail", "version": "v1"} in services


def test_mime_message_has_inline_images(
    app: Flask, conn: sqlite3.Connection, demo_settings: Settings
) -> None:
    export = _email(app, conn, demo_settings)
    data = json.loads(package_json(export))
    message = message_from_bytes(base64.urlsafe_b64decode(data["raw"]), policy=policy.default)
    assert message["Subject"] == "News Franchise — Janvier 2000"
    assert message.get_content_type() == "multipart/alternative"
    plain, related = message.get_payload()
    assert plain.get_content_type() == "text/plain"
    # Fins de ligne CRLF : norme des e-mails.
    assert plain.get_content().replace("\r\n", "\n") == export.text
    assert related.get_content_type() == "multipart/related"
    html, *images = related.get_payload()
    assert (
        html.get_content_type() == "text/html"
        and html.get_content().replace("\r\n", "\n").strip() == export.html.strip()
    )
    # Chaque image appelée par cid: dans le HTML est jointe, en ligne, avec son Content-ID.
    by_cid = {part["Content-ID"].strip("<>"): part for part in images}
    assert set(by_cid) == set(re.findall(r'src="cid:([^"]+)"', export.html))
    for image in export.images:
        part = by_cid[image.cid]
        assert part.get_content_disposition() == "inline"
        assert part.get_content_type() == image.mime_type
        assert part.get_content() == image.data
    assert {"nf-photo-1", "nf-photo-2", "nf-photo-3"} <= set(by_cid)  # photos des ouvertures


def test_shape_png_are_transparent() -> None:
    for kind in shapes.SHAPES:
        with Image.open(io.BytesIO(shapes.shape_png(kind, "#EF4050", 44))) as image:
            assert image.mode == "RGBA" and image.size == (44, 44)
            # Fond transparent autour de la forme, forme opaque.
            assert image.getchannel("A").getextrema() == (0, 255)
    with Image.open(io.BytesIO(shapes.motif_png("#FFFFFF"))) as motif:
        assert motif.size == (420, 450)


# --------------------------------------------------------------------------- pages


def test_export_pages(client: FlaskClient, demo_settings: Settings) -> None:
    html = _html(client.get("/exports"))
    assert "Janvier 2000" in html and "jamais" in html
    page = client.get("/newsletters/2000-01/export")
    assert page.status_code == 200 and "Préparer l'e-mail" in _html(page)
    assert 'href="/newsletters/2000-01/export"' in _html(
        client.get("/newsletters/2000-01/rubrique-1")
    )

    assert client.post("/newsletters/2000-01/export/email").status_code == 400  # sans jeton CSRF
    response = post_form(client, "/newsletters/2000-01/export/email", follow_redirects=True)
    html = _html(response)
    assert "E-mail préparé" in html and "Dernier e-mail préparé" in html
    assert "pas encore marquée comme relue" in html
    assert "news-franchise-2000-01.json" in html

    preview = client.get("/newsletters/2000-01/export/email/apercu")
    assert preview.status_code == 200 and b'src="images/nf-logo.png"' in preview.data
    assert client.get("/newsletters/2000-01/export/email/images/nf-logo.png").status_code == 200
    package = client.get("/newsletters/2000-01/export/email/paquet")
    assert package.status_code == 200
    assert "attachment" in package.headers["Content-Disposition"]
    assert json.loads(package.data)["format"] == PACKAGE_FORMAT


@pytest.mark.parametrize(
    "url",
    [
        "/newsletters/2000-01/export/email/images/..%2Fnews-franchise-2000-01.json",
        "/newsletters/2000-01/export/email/images/absente.png",
        "/newsletters/2000-01/export/email/images/nf-logo.svg",
        "/newsletters/2099-01/export",
        "/newsletters/2000-13/export",
    ],
)
def test_export_files_are_protected(client: FlaskClient, demo_settings: Settings, url: str) -> None:
    post_form(client, "/newsletters/2000-01/export/email")
    assert client.get(url).status_code == 404


def test_export_before_preparing(client: FlaskClient, demo_settings: Settings) -> None:
    assert client.get("/newsletters/2000-01/export/email/apercu").status_code == 404
    assert client.get("/newsletters/2000-01/export/email/paquet").status_code == 404


def test_export_of_empty_month_explains(client: FlaskClient, newsletter: Newsletter) -> None:
    html = _html(post_form(client, "/newsletters/2026-10/export/email", follow_redirects=True))
    assert "encore vide" in html
    assert "Dernier e-mail préparé" not in html


# --------------------------------------------------------------------------- bouton Imprimer

FAKE_PDF = b"%PDF-1.4 version de test"


def test_print_button_links_to_the_pdf(
    app: Flask, conn: sqlite3.Connection, demo_settings: Settings
) -> None:
    with app.app_context():
        export = build_email(conn, "2000-01", demo_settings, make_print_pdf=lambda v, t: FAKE_PDF)
    token = email_module.PRINT_LINK_TOKEN
    assert export.print_pdf == FAKE_PDF and export.warnings == ()
    # Bouton en haut et lien en pied de page, vers le lien provisoire (remplacé par le script).
    assert export.html.count(f'href="{token}"') == 2
    assert "Imprimer la newsletter (PDF)" in export.html
    assert f"Imprimer la newsletter (PDF) : {token}" in export.text
    # Version navigateur : le bouton ouvre le PDF voisin.
    assert export.browser_html.count('href="news-franchise-2000-01.pdf"') == 2

    data = json.loads(package_json(export))
    assert data["printLinkToken"] == token
    assert data["printPdf"]["fileName"] == "news-franchise-2000-01.pdf"
    assert base64.b64decode(data["printPdf"]["data"]) == FAKE_PDF
    # Texte et HTML lisibles tels quels dans le message (8bit) : le script peut remplacer le
    # lien provisoire ; lignes de moins de 998 octets (norme des e-mails).
    raw = base64.urlsafe_b64decode(data["raw"])
    assert raw.count(token.encode()) == 3
    assert max(len(line) for line in raw.split(b"\r\n")) <= 998
    message = message_from_bytes(raw, policy=policy.default)
    for part in message.walk():
        if part.get_content_maintype() == "text":
            assert part["Content-Transfer-Encoding"] == "8bit"
    # Remplacement tel que le fait le script : le message reste valide, images comprises.
    link = "https://drive.google.com/file/d/abc/view?usp=drivesdk"
    fixed = message_from_bytes(raw.replace(token.encode(), link.encode()), policy=policy.default)
    html_part = next(p for p in fixed.walk() if p.get_content_type() == "text/html")
    assert html_part.get_content().count(f'href="{link}"') == 2
    images = [p for p in fixed.walk() if p.get_content_maintype() == "image"]
    assert {p.get_content() for p in images} == {i.data for i in export.images}


def test_no_print_button_without_pdf(
    app: Flask, conn: sqlite3.Connection, demo_settings: Settings
) -> None:
    from news_franchise.newsletter.pdf import PdfError

    def failing(view: object, theme: object) -> bytes:
        raise PdfError("Aucun navigateur Edge ou Chrome trouvé.")

    with app.app_context():
        export = build_email(conn, "2000-01", demo_settings, make_print_pdf=failing)
        plain = build_email(conn, "2000-01", demo_settings)
    for result in (export, plain):
        assert result.print_pdf is None
        assert email_module.PRINT_LINK_TOKEN not in result.html + result.text
        assert json.loads(package_json(result))["printPdf"] is None
    assert len(export.warnings) == 1 and "sans bouton « Imprimer »" in export.warnings[0]


def test_export_page_with_print_pdf(
    client: FlaskClient, demo_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from news_franchise.newsletter import views

    monkeypatch.setattr(views, "newsletter_pdf", lambda view, theme, settings: FAKE_PDF)
    html = _html(post_form(client, "/newsletters/2000-01/export/email", follow_redirects=True))
    assert "news-franchise-2000-01.pdf" in html and "Imprimer la newsletter" in html
    pdf = client.get("/newsletters/2000-01/export/email/news-franchise-2000-01.pdf")
    assert pdf.status_code == 200 and pdf.data == FAKE_PDF
    assert pdf.mimetype == "application/pdf"
    assert client.get("/newsletters/2000-01/export/email/autre.pdf").status_code == 404
    folder = demo_settings.exports_dir / "2000-01" / "email"
    assert (folder / "news-franchise-2000-01.pdf").read_bytes() == FAKE_PDF
