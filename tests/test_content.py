"""Tests du contenu interne (étape 7) : Une, ouvertures et photos, rencontres, plans."""

from __future__ import annotations

import io
import re
import sqlite3
from pathlib import Path

import pytest
import respx
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from news_franchise.config import Settings
from news_franchise.content.photos import MAX_SIDE, PhotoError, process_photo
from news_franchise.models import Franchisee, Meeting, Newsletter, Opening
from news_franchise.repositories import franchisees, meetings, newsletters, openings
from news_franchise.tools import demo
from tests.helpers import post_form

BASE = "/newsletters/2026-10"


def _html(response: object) -> str:
    return response.get_data(as_text=True)  # type: ignore[attr-defined]


def image_bytes(fmt: str, size: tuple[int, int] = (2400, 1800), **save: object) -> bytes:
    mode = "RGBA" if fmt == "PNG" else "RGB"
    image = Image.new(mode, size, (30, 120, 200, 128) if mode == "RGBA" else (30, 120, 200))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save)
    return buffer.getvalue()


def jpeg_with_exif(orientation: int = 6) -> bytes:
    image = Image.new("RGB", (3000, 2000), (200, 30, 30))
    exif = image.getexif()
    exif[0x0112] = orientation  # rotation de 90°
    exif[0x8825] = {1: "N", 2: (48.0, 51.0, 24.0), 3: "E", 4: (2.0, 21.0, 3.0)}  # GPS
    exif[0x010F] = "Fabricant"
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif.tobytes())
    return buffer.getvalue()


@pytest.fixture
def opening(conn: sqlite3.Connection, newsletter: Newsletter) -> Opening:
    assert newsletter.id is not None
    return openings.add(
        conn, Opening(newsletter_id=newsletter.id, brand_name="Pokawa", location="CC Test, Lyon")
    )


def upload(client: FlaskClient, opening_id: int, files: list[tuple[bytes, str]]) -> object:
    data = {"photos": [(io.BytesIO(content), name) for content, name in files]}
    return post_form(
        client, f"{BASE}/ouvertures/{opening_id}/photos", data, content_type="multipart/form-data"
    )


# --------------------------------------------------------------------------- onglets et Une


def test_tab_order_and_front_page(
    client: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    nid = newsletter.id
    assert nid is not None
    openings.add(conn, Opening(newsletter_id=nid, brand_name="Pokawa", location="Lyon"))
    for name in ("Leonidas", "Wycon", "leonidas"):
        meetings.add(conn, Meeting(newsletter_id=nid, brand_name=name))
    source = {"source_name": "S", "source_url": "https://a.example/x", "confidence": "basse"}
    franchisees.add(conn, Franchisee(newsletter_id=nid, name="Validé", validated=True, **source))
    franchisees.add(conn, Franchisee(newsletter_id=nid, name="À valider", **source))

    html = _html(client.get(f"{BASE}/une"))
    labels = [
        "Une",
        "1. Marché",
        "2. Nos enseignes",
        "3. Ouvertures",
        "4. Enseignes rencontrées",
        "5. Franchisés",
        "6. Plans de développement",
    ]
    nav = html[html.index('aria-label="Rubriques"') :]
    positions = [nav.index(f"\n      {label}\n") for label in labels]
    assert positions == sorted(positions)
    assert "Ces chiffres se mettent à jour automatiquement" in html
    numbers = re.findall(r'figure-number">(\d+)<', html)
    assert numbers == ["1", "2", "1"]
    assert 'figure-label">ouverture<' in html  # singulier
    assert 'figure-label">enseignes rencontrées<' in html
    assert 'figure-label">franchisé identifié<' in html
    assert "1 suggestion\n          encore à valider, non comptée." in html
    assert f'href="{BASE}/ouvertures"' in html and f'href="{BASE}/franchises"' in html


def test_home_internal_content_button(client: FlaskClient, conn: sqlite3.Connection) -> None:
    assert 'href="/contenu-interne"' in _html(client.get("/"))
    response = client.get("/contenu-interne")
    assert response.headers["Location"].endswith("/newsletters/")
    newsletters.get_or_create(conn, "2026-09")
    reviewed = newsletters.get_or_create(conn, "2026-10")
    newsletters.set_status(conn, reviewed.id, "reviewed")  # type: ignore[arg-type]
    response = client.get("/contenu-interne")
    assert response.headers["Location"].endswith("/newsletters/2026-09/ouvertures")


# --------------------------------------------------------------------------- ouvertures


def test_opening_add_edit_move_delete(
    client: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    refused = post_form(
        client,
        f"{BASE}/ouvertures/ajouter",
        {"enseigne": "Pokawa", "lieu": "", "description": "Texte gardé"},
    )
    assert refused.status_code == 400
    assert 'id="new-lieu-err"' in _html(refused) and "Texte gardé" in _html(refused)

    post_form(
        client,
        f"{BASE}/ouvertures/ajouter",
        {"enseigne": "Pokawa", "lieu": "CC A, Lyon", "date": "2026-10-03"},
    )
    response = post_form(
        client,
        f"{BASE}/ouvertures/ajouter",
        {
            "enseigne": "autre",
            "enseigne_autre": "Burger Démo",
            "lieu": "CC B, Nice",
            "date": "2026-07-01",
        },
    )
    assert response.status_code == 302
    assert "ne tombe ni dans le mois" in _html(client.get(f"{BASE}/ouvertures"))
    first, second = openings.list_for_newsletter(conn, newsletter.id)  # type: ignore[arg-type]
    assert second.brand_name == "Burger Démo"

    post_form(
        client,
        f"{BASE}/ouvertures/{first.id}",
        {"enseigne": "Wycon", "lieu": "CC A, Lyon", "description": "x" * 401},
    )
    assert openings.get(conn, first.id).brand_name == "Pokawa"  # type: ignore[union-attr, arg-type]
    post_form(
        client,
        f"{BASE}/ouvertures/{first.id}",
        {"enseigne": "Wycon", "lieu": "CC A, Lyon", "description": "Belle ouverture"},
    )
    assert openings.get(conn, first.id).brand_name == "Wycon"  # type: ignore[union-attr, arg-type]

    post_form(client, f"{BASE}/ouvertures/{second.id}/deplacer", {"sens": "tete"})
    assert [o.id for o in openings.list_for_newsletter(conn, newsletter.id)] == [
        second.id,
        first.id,
    ]  # type: ignore[arg-type]

    upload(client, second.id, [(image_bytes("JPEG"), "a.jpg")])  # type: ignore[arg-type]
    [photo] = openings.list_photos(conn, second.id)  # type: ignore[arg-type]
    photo_path = settings.photos_dir / photo.file_name
    assert photo_path.is_file()
    assert "cette ouverture" in _html(client.get(f"{BASE}/ouvertures/{second.id}/supprimer"))
    post_form(client, f"{BASE}/ouvertures/{second.id}/supprimer", {})
    assert openings.get(conn, second.id) is None  # type: ignore[arg-type]
    assert not photo_path.exists()


# --------------------------------------------------------------------------- photos


def test_photo_formats_resize_and_limit(
    client: FlaskClient, conn: sqlite3.Connection, opening: Opening, settings: Settings
) -> None:
    response = upload(
        client,
        opening.id,  # type: ignore[arg-type]
        [
            (image_bytes("JPEG"), "facade.jpg"),
            (image_bytes("PNG", (3000, 1000)), "vitrine.png"),
            (image_bytes("WEBP", (800, 600)), "interieur.webp"),
        ],
    )
    assert response.status_code == 302  # type: ignore[attr-defined]
    photos = openings.list_photos(conn, opening.id)  # type: ignore[arg-type]
    assert len(photos) == 3
    for photo, original in zip(
        photos, ("facade.jpg", "vitrine.png", "interieur.webp"), strict=True
    ):
        assert photo.file_name.startswith("2026-10/") and photo.file_name.endswith(".jpg")
        assert original not in photo.file_name
        with Image.open(settings.photos_dir / photo.file_name) as stored:
            assert stored.format == "JPEG" and max(stored.size) <= MAX_SIDE
    with Image.open(settings.photos_dir / photos[0].file_name) as stored:
        assert stored.size == (1600, 1200)
    with Image.open(settings.photos_dir / photos[2].file_name) as stored:
        assert stored.size == (800, 600)  # jamais agrandie

    fourth = upload(client, opening.id, [(image_bytes("JPEG"), "quatre.jpg")])  # type: ignore[arg-type]
    assert fourth.status_code == 302  # type: ignore[attr-defined]
    assert len(openings.list_photos(conn, opening.id)) == 3  # type: ignore[arg-type]
    assert "3 photos au maximum par ouverture" in _html(client.get(f"{BASE}/ouvertures"))


def test_fake_and_unsupported_images_are_refused(
    client: FlaskClient, conn: sqlite3.Connection, opening: Opening
) -> None:
    gif = io.BytesIO()
    Image.new("RGB", (10, 10)).save(gif, format="GIF")
    upload(
        client,
        opening.id,  # type: ignore[arg-type]
        [
            (b"Ceci est un texte, pas une photo.", "piege.jpg"),
            (gif.getvalue(), "anim.gif"),
            (image_bytes("JPEG"), "vraie.jpg"),
        ],
    )
    html = _html(client.get(f"{BASE}/ouvertures"))
    assert "« piege.jpg » n&#39;est pas une image lisible" in html
    assert "« anim.gif » n&#39;est pas une photo JPEG, PNG ou WebP" in html
    assert len(openings.list_photos(conn, opening.id)) == 1  # type: ignore[arg-type]


def test_upload_over_15_mb_is_refused(client: FlaskClient, opening: Opening) -> None:
    big = b"\xff" * (15 * 1024 * 1024 + 1)
    response = upload(client, opening.id, [(big, "enorme.jpg")])  # type: ignore[arg-type]
    assert response.status_code == 413  # type: ignore[attr-defined]
    assert "dépasse 15 Mo" in _html(response)


def test_exif_removed_and_orientation_applied(tmp_path: Path) -> None:
    saved = process_photo(jpeg_with_exif(6), tmp_path, "2026-10", "telephone.jpg")
    with Image.open(tmp_path / saved.file_name) as stored:
        assert stored.size == (1067, 1600)  # 3000 × 2000 tourné d'un quart de tour, réduit
        assert not stored.getexif()
        assert "exif" not in stored.info
    raw = (tmp_path / saved.file_name).read_bytes()
    assert b"Exif" not in raw and b"Fabricant" not in raw
    with pytest.raises(PhotoError):
        process_photo(b"", tmp_path, "2026-10", "vide.jpg")


def test_main_photo_caption_and_delete(
    client: FlaskClient, conn: sqlite3.Connection, opening: Opening, settings: Settings
) -> None:
    upload(client, opening.id, [(image_bytes("JPEG"), "1.jpg"), (image_bytes("JPEG"), "2.jpg")])  # type: ignore[arg-type]
    first, second = openings.list_photos(conn, opening.id)  # type: ignore[arg-type]
    html = _html(client.get(f"{BASE}/ouvertures"))
    assert html.count("★ Photo principale") == 1
    post_form(client, f"{BASE}/photos/{second.id}/principale", {})
    assert [p.id for p in openings.list_photos(conn, opening.id)] == [second.id, first.id]  # type: ignore[arg-type]
    post_form(client, f"{BASE}/photos/{second.id}/legende", {"legende": "Vue de la façade"})
    assert openings.get_photo(conn, second.id).caption == "Vue de la façade"  # type: ignore[union-attr, arg-type]
    path = settings.photos_dir / first.file_name
    assert "cette photo" in _html(client.get(f"{BASE}/photos/{first.id}/supprimer"))
    post_form(client, f"{BASE}/photos/{first.id}/supprimer", {})
    assert not path.exists() and openings.get_photo(conn, first.id) is None  # type: ignore[arg-type]


def test_photo_route_cannot_leave_photos_dir(
    client: FlaskClient, conn: sqlite3.Connection, opening: Opening, settings: Settings
) -> None:
    upload(client, opening.id, [(image_bytes("JPEG"), "a.jpg")])  # type: ignore[arg-type]
    [photo] = openings.list_photos(conn, opening.id)  # type: ignore[arg-type]
    ok = client.get(f"/photos/{photo.file_name}")
    assert ok.status_code == 200 and ok.mimetype == "image/jpeg"
    assert (settings.db_dir / "news_franchise.sqlite3").is_file()
    secret = settings.data_dir / "secret.jpg"
    secret.write_bytes(b"secret")
    for path in (
        "/photos/../db/news_franchise.sqlite3",
        "/photos/..%2Fdb%2Fnews_franchise.sqlite3",
        "/photos/%2e%2e/secret.jpg",
        "/photos/2026-10/../../secret.jpg",
        f"/photos/{settings.data_dir / 'secret.jpg'}",
        "/photos//etc/passwd",
        "/photos/C:%5CWindows%5Cwin.ini",
        "/photos/2026-10/inexistante.jpg",
    ):
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 404, path
        assert b"secret" not in response.data


def test_csrf_required_on_new_forms(
    client: FlaskClient, opening: Opening, conn: sqlite3.Connection
) -> None:
    files = {"photos": [(io.BytesIO(image_bytes("JPEG")), "a.jpg")]}
    assert client.post(f"{BASE}/ouvertures/{opening.id}/photos", data=files).status_code == 400
    for url, data in [
        (f"{BASE}/ouvertures/ajouter", {"enseigne": "Pokawa", "lieu": "L"}),
        (f"{BASE}/rencontres/ajouter", {"enseigne": "Pokawa"}),
        (f"{BASE}/rencontres/ajout-rapide", {"liste": "Pokawa"}),
        (f"{BASE}/plans/enregistrer", {"lien": "https://example.com/plans"}),
        (f"{BASE}/plans/retirer", {}),
        (f"{BASE}/ouvertures/{opening.id}/supprimer", {}),
    ]:
        assert client.post(url, data=data).status_code == 400, url
    assert openings.list_photos(conn, opening.id) == []  # type: ignore[arg-type]
    assert meetings.list_for_newsletter(conn, opening.newsletter_id) == []


# --------------------------------------------------------------------------- enseignes rencontrées


def test_meetings_unit_and_quick_add(
    client: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    nid = newsletter.id
    post_form(
        client,
        f"{BASE}/rencontres/ajouter",
        {"enseigne": "Pokawa", "date": "2026-10-02", "commentaire": "Très intéressée"},
    )
    duplicate = post_form(client, f"{BASE}/rencontres/ajouter", {"enseigne": "POKAWA"})
    assert duplicate.status_code == 400 and "déjà dans la liste" in _html(duplicate)
    assert 'list="enseignes-suivies"' in _html(client.get(f"{BASE}/rencontres"))

    response = post_form(
        client,
        f"{BASE}/rencontres/ajout-rapide",
        {"liste": "pokawa\n\n  Léonidas  \nleonidas\nCrêpe Touch\n"},
    )
    assert response.status_code == 302
    names = [m.brand_name for m in meetings.list_for_newsletter(conn, nid)]  # type: ignore[arg-type]
    assert names == ["Pokawa", "Léonidas", "Crêpe Touch"]
    html = _html(client.get(f"{BASE}/rencontres"))
    assert "2 enseigne(s) ajoutée(s) : Léonidas, Crêpe Touch." in html
    assert "Déjà dans la liste, donc ignorée(s) : pokawa, leonidas." in html

    empty = post_form(client, f"{BASE}/rencontres/ajout-rapide", {"liste": "\n  \n"})
    assert empty.status_code == 400 and 'id="liste-err"' in _html(empty)

    crepe = meetings.list_for_newsletter(conn, nid)[-1]  # type: ignore[arg-type]
    post_form(client, f"{BASE}/rencontres/{crepe.id}/deplacer", {"sens": "tete"})
    assert meetings.list_for_newsletter(conn, nid)[0].brand_name == "Crêpe Touch"  # type: ignore[arg-type]
    post_form(
        client,
        f"{BASE}/rencontres/{crepe.id}",
        {"enseigne": "Crêpe Touch", "commentaire": "x" * 201},
    )
    assert meetings.get(conn, crepe.id).comment is None  # type: ignore[union-attr, arg-type]
    post_form(
        client,
        f"{BASE}/rencontres/{crepe.id}",
        {"enseigne": "Crêpe Touch", "commentaire": "Rendez-vous au salon"},
    )
    assert meetings.get(conn, crepe.id).comment == "Rendez-vous au salon"  # type: ignore[union-attr, arg-type]
    post_form(client, f"{BASE}/rencontres/{crepe.id}/supprimer", {})
    assert meetings.get(conn, crepe.id) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- plans


def test_plans_link(
    client: FlaskClient,
    conn: sqlite3.Connection,
    newsletter: Newsletter,
    mock_http: respx.MockRouter,
) -> None:
    link = "https://carmila.sharepoint.example/sites/franchise/plans.pdf"
    response = post_form(client, f"{BASE}/plans/enregistrer", {"lien": link, "libelle": ""})
    assert response.status_code == 302
    assert len(mock_http.calls) == 0  # le lien n'est jamais appelé
    saved = newsletters.get(conn, "2026-10")
    assert saved is not None and saved.development_plans_url == link
    assert saved.development_plans_label is None
    html = _html(client.get(f"{BASE}/plans"))
    assert "Voir les plans de développement" in html and "Ouvrir le lien" in html

    for bad in ("javascript:alert(1)", "ftp://serveur/plans.pdf", "plans.pdf"):
        refused = post_form(
            client, f"{BASE}/plans/enregistrer", {"lien": bad, "libelle": "Mes plans"}
        )
        assert refused.status_code == 400, bad
        assert 'id="plans-lien-err"' in _html(refused) and 'value="Mes plans"' in _html(refused)
    assert newsletters.get(conn, "2026-10").development_plans_url == link  # type: ignore[union-attr]

    post_form(client, f"{BASE}/plans/enregistrer", {"lien": link, "libelle": "Plans 2027"})
    assert newsletters.get(conn, "2026-10").development_plans_label == "Plans 2027"  # type: ignore[union-attr]
    post_form(client, f"{BASE}/plans/retirer", {})
    cleared = newsletters.get(conn, "2026-10")
    assert cleared is not None and cleared.development_plans_url is None
    assert cleared.development_plans_label is None


# ------------------------------------------------------------------------ statut et démonstration


def test_mark_reviewed_new_warnings(
    client: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    post_form(client, f"{BASE}/statut", {"statut": "relue", "onglet": "ouvertures"})
    assert newsletters.get(conn, "2026-10").status == "reviewed"  # type: ignore[union-attr]
    html = _html(client.get(f"{BASE}/ouvertures"))
    assert "Aucune ouverture saisie" in html
    assert "Aucune enseigne rencontrée saisie" in html
    assert "Pas de lien vers les plans de développement" in html


def test_demo_internal_content(settings: Settings, conn: sqlite3.Connection, app: Flask) -> None:
    from news_franchise.repositories import brands

    brands.sync_from_yaml(conn)
    assert demo.main([], settings=settings, out=lambda _: None) == 0
    newsletter = newsletters.get(conn, "2000-01")
    assert (
        newsletter is not None
        and newsletter.development_plans_url == "https://example.com/demo/plans"
    )
    demo_openings = openings.list_for_newsletter(conn, newsletter.id)  # type: ignore[arg-type]
    assert len(demo_openings) == 2
    assert [len(openings.list_photos(conn, o.id)) for o in demo_openings] == [2, 1]  # type: ignore[arg-type]
    assert len(meetings.list_for_newsletter(conn, newsletter.id)) == 4  # type: ignore[arg-type]
    files = list((settings.photos_dir / "2000-01").glob("*.jpg"))
    assert len(files) == 3
    assert demo.main(["--reset"], settings=settings, out=lambda _: None) == 0
    assert len(list((settings.photos_dir / "2000-01").glob("*.jpg"))) == 3  # anciennes supprimées
