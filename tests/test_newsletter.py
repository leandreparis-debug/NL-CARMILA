"""Tests de l'étape 8 : thème, dates en français, vue de la newsletter, QR codes, aperçu."""

from __future__ import annotations

import re
import sqlite3
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image

from news_franchise.config import Settings
from news_franchise.models import Article, Franchisee, Meeting, Newsletter, Opening
from news_franchise.newsletter import qr, shapes
from news_franchise.newsletter.dates import format_day, format_month
from news_franchise.newsletter.theme import (
    THEME_FILE,
    ThemeError,
    contrast_ratio,
    load_theme,
)
from news_franchise.newsletter.view import (
    EmptyNewsletterError,
    NewsletterNotFoundError,
    build_newsletter_view,
)
from news_franchise.repositories import (
    articles,
    franchisees,
    meetings,
    newsletters,
    openings,
)
from news_franchise.tools import demo

SVG_NS = "{http://www.w3.org/2000/svg}"


def _html(response: object) -> str:
    return response.get_data(as_text=True)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- thème


def write_theme(tmp_path: Path, **overrides: str) -> Path:
    """Copie du thème par défaut dans tmp_path, logo compris, avec des valeurs remplacées
    (clé « colors.text », « logo »…)."""
    logo = tmp_path / "logo.png"
    Image.new("RGB", (60, 20), (29, 53, 87)).save(logo)
    text = THEME_FILE.read_text(encoding="utf-8")
    logo_value = overrides.pop("logo", logo.as_posix())
    text = text.replace("logo: config/assets/logo-carmila.png", f"logo: {logo_value}")
    text = text.replace(
        "logo_reverse: config/assets/logo-carmila-blanc.png", f"logo_reverse: {logo.as_posix()}"
    )
    for key, value in overrides.items():
        section, _, name = key.rpartition(".")
        assert section in ("colors", "fonts", "section_colors")
        pattern = rf"(\n{section}:\n(?:  .*\n|\s*#.*\n)*?  {name}: )\"[^\"]*\""
        text, count = re.subn(pattern, rf'\1"{value}"', text, count=1)
        assert count == 1, key
    path = tmp_path / "theme.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_default_theme_loads() -> None:
    theme = load_theme()
    assert theme.colors["background"] == "#FFFFFF"
    assert re.fullmatch(r"#[0-9A-F]{6}", theme.colors["primary"])
    assert theme.logo.is_file() and theme.logo_reverse.is_file()
    assert theme.logo_alt == "Carmila"
    assert set(theme.section_colors) == set(theme.section_titles)
    assert set(theme.section_titles) == {"une", *(f"rubrique_{n}" for n in range(1, 7))}
    assert theme.font_body.endswith("sans-serif")
    assert theme.warnings() == []


def test_invalid_color_gives_clear_error(tmp_path: Path) -> None:
    path = write_theme(tmp_path, **{"colors.primary": "#12"})
    with pytest.raises(ThemeError, match=r"colors\.primary.*#RRGGBB.*'#12'"):
        load_theme(path, project_dir=tmp_path)


def test_missing_logo_gives_clear_error(tmp_path: Path) -> None:
    path = write_theme(tmp_path, logo="assets/absent.png")
    with pytest.raises(ThemeError, match="logo introuvable : assets/absent.png"):
        load_theme(path, project_dir=tmp_path)


def test_unsafe_font_is_refused(tmp_path: Path) -> None:
    path = write_theme(tmp_path, **{"fonts.body": "Arial; } body { color: red"})
    with pytest.raises(ThemeError, match="fonts.body"):
        load_theme(path, project_dir=tmp_path)


def test_low_contrast_is_a_warning_not_an_error(tmp_path: Path) -> None:
    path = write_theme(tmp_path, **{"colors.muted": "#777777"})
    theme = load_theme(path, project_dir=tmp_path)  # non bloquant
    assert round(contrast_ratio("#777777", "#FFFFFF"), 2) == 4.48
    warnings = theme.warnings()
    # Sur le fond blanc (4,48:1) et sur les encadrés crème (3,98:1).
    assert len(warnings) == 2
    assert "Texte secondaire sur le fond" in warnings[0] and "4,48:1" in warnings[0]
    assert "Texte secondaire sur les encadrés" in warnings[1]


def test_large_text_uses_the_3_to_1_minimum(tmp_path: Path) -> None:
    # Blanc sur le rouge Carmila : 3,8:1, suffisant pour le grand texte du bandeau.
    assert round(contrast_ratio("#FFFFFF", "#EF4050"), 1) == 3.8
    assert load_theme().warnings() == []
    # Un rouge plus clair passe sous 3:1 : avertissement.
    path = write_theme(tmp_path, **{"colors.primary": "#FF8A95"})
    warnings = load_theme(path, project_dir=tmp_path).warnings()
    assert any("bandeau" in w and "minimum conseillé 3:1" in w for w in warnings)


def test_section_number_color_is_the_most_readable() -> None:
    theme = load_theme()
    assert theme.accent("rubrique_1").on_color == "#FFFFFF"  # sur rouge
    assert theme.accent("rubrique_3").on_color == "#004D46"  # sur orange clair
    assert all(check.ok for check in theme.contrast_checks())


def test_invalid_section_color_and_missing_font(tmp_path: Path) -> None:
    path = write_theme(tmp_path, **{"section_colors.rubrique_2": "turquoise"})
    with pytest.raises(ThemeError, match=r"section_colors\.rubrique_2"):
        load_theme(path, project_dir=tmp_path)
    path = write_theme(tmp_path)
    path.write_text(
        re.sub(r"\n  labels: .*", "", path.read_text(encoding="utf-8")), encoding="utf-8"
    )
    with pytest.raises(ThemeError, match="fonts.labels"):
        load_theme(path, project_dir=tmp_path)


def test_theme_css_variables_come_from_theme() -> None:
    css = load_theme().css_variables()
    assert "--nf-primary: #EF4050;" in css
    assert "--nf-opportunity-text: #004D46;" in css
    assert "--nf-font-body: 'Century Gothic'," in css
    assert "--nf-font-labels: 'Bahnschrift Condensed'," in css


@pytest.mark.parametrize("kind", shapes.SHAPES)
def test_shapes_are_valid_svg(kind: str) -> None:
    root = ET.fromstring(shapes.shape_svg(kind, "#EF4050"))
    assert root.tag == f"{SVG_NS}svg" and root.get("aria-hidden") == "true"
    assert root.find(f"{SVG_NS}path").get("fill") == "#EF4050"  # type: ignore[union-attr]


def test_motif_is_valid_svg_with_diagonal_edge() -> None:
    svg = shapes.motif_svg("#FFFFFF", columns=4, rows=4)
    root = ET.fromstring(svg)
    path = root.find(f"{SVG_NS}path")
    assert path is not None
    # Colonnes de 1, 2, 3 puis 4 formes (bord en diagonale) : 10 formes, dont 3 nœuds
    # dessinés chacun en deux sous-chemins.
    assert path.get("d", "").count("M") == 10 + 3
    with pytest.raises(ValueError):
        shapes.shape_path("cercle", 0, 0, 10)


# --------------------------------------------------------------------------- dates


def test_first_day_of_month_is_written_1er() -> None:
    assert format_day(date(2026, 1, 1)) == "1er janvier 2026"
    assert format_day(date(2026, 10, 12)) == "12 octobre 2026"


def test_months_with_accents_and_capital() -> None:
    assert format_month("2026-10") == "Octobre 2026"
    assert format_day(date(2026, 2, 3)) == "3 février 2026"
    assert format_month("2026-08") == "Août 2026"
    assert format_month("2026-12") == "Décembre 2026"


def test_datetime_is_formatted_in_paris_time() -> None:
    # 31 décembre 23 h 30 UTC = 1er janvier 0 h 30 à Paris.
    assert format_day(datetime(2025, 12, 31, 23, 30, tzinfo=UTC)) == "1er janvier 2026"


# --------------------------------------------------------------------------- vue


def _article(newsletter: Newsletter, rubric: int, n: int, **kwargs: object) -> Article:
    values: dict[str, object] = {
        "title": f"Titre {n}",
        "source_name": "Source test",
        "url": f"https://example.com/a{n}",
        "published_at": datetime(2026, 10, n, 8, tzinfo=UTC),
    }
    values.update(kwargs)
    return Article(newsletter_id=newsletter.id, rubric=rubric, **values)  # type: ignore[arg-type]


def _fill(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    """Contenu varié : articles retenus ou non, franchisés validés ou non, une rencontre."""
    assert newsletter.id is not None
    for n, selected in ((1, True), (2, False), (3, True)):
        articles.add(conn, _article(newsletter, 1, n, selected=selected))
    articles.add(conn, _article(newsletter, 2, 4, is_opportunity=True))
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
    franchisees.add(
        conn,
        Franchisee(
            newsletter_id=newsletter.id,
            name="Non Validé",
            source_name="Source test",
            source_url="https://example.com/a1",
        ),
    )
    franchisees.add(
        conn,
        Franchisee(
            newsletter_id=newsletter.id,
            name="Bob Test",
            source_name="Source test",
            source_url="https://example.com/a3",
            store_count=12,
            validated=True,
        ),
    )
    meetings.add(conn, Meeting(newsletter_id=newsletter.id, brand_name="Pokawa"))


def test_view_keeps_only_retained_and_validated_in_order(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    _fill(conn, newsletter)
    view = build_newsletter_view(conn, "2026-10", settings)
    section1, section2, section3, section4, section5, section6 = view.sections
    assert [item.title for item in section1.items] == ["Titre 1", "Titre 3"]
    assert section1.items[0].date_label == "1er octobre 2026"
    assert section2.items[0].opportunity is True
    assert [item.name for item in section5.items] == ["Alice Test", "Bob Test"]
    assert section3.hidden and section6.hidden
    assert not section4.hidden
    assert view.month_label == "Octobre 2026"


def test_view_hides_empty_sections_and_counts_toc(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    _fill(conn, newsletter)
    view = build_newsletter_view(conn, "2026-10", settings)
    assert [s.number for s in view.visible_sections] == [1, 2, 4, 5]
    # Numéros affichés sans trou quand une rubrique vide est masquée.
    assert [s.display_number for s in view.visible_sections] == [1, 2, 3, 4]
    assert [(e.number, e.title, e.count_label) for e in view.toc] == [
        (1, "Marché de la franchise", "2 articles"),
        (2, "Nos enseignes", "1 article"),
        (3, "Enseignes rencontrées", "1 enseigne"),
        (4, "Franchisés identifiés", "2 franchisés"),
    ]


def test_front_page_matches_front_page_figures(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    _fill(conn, newsletter)
    assert newsletter.id is not None
    view = build_newsletter_view(conn, "2026-10", settings)
    figures = newsletters.front_page_figures(conn, newsletter.id)
    assert [f.value for f in view.front] == [
        figures.openings,
        figures.brands_met,
        figures.franchisees,
    ]
    assert [f.label for f in view.front] == [
        "ouverture",
        "enseigne rencontrée",
        "franchisés identifiés",
    ]
    # Pas de lien vers la rubrique des ouvertures, vide donc absente.
    assert [f.anchor for f in view.front] == [None, "rubrique-4", "rubrique-5"]


def test_store_count_shown_only_when_known(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings, client: FlaskClient
) -> None:
    _fill(conn, newsletter)
    view = build_newsletter_view(conn, "2026-10", settings)
    alice, bob = view.sections[4].items
    assert alice.store_count_label is None
    assert bob.store_count_label == "12 points de vente"
    html = _html(client.get("/newsletters/2026-10/apercu"))
    block = html[html.index("Alice Test") : html.index("Bob Test")]
    assert "None" not in block and "point de vente" not in block and ">0<" not in block
    assert "12 points de vente" in html


def test_empty_newsletter_raises_clear_error(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    with pytest.raises(EmptyNewsletterError, match="Octobre 2026 est encore vide"):
        build_newsletter_view(conn, "2026-10", settings)
    with pytest.raises(NewsletterNotFoundError):
        build_newsletter_view(conn, "2026-11", settings)


def test_opening_main_photo_is_first(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    from news_franchise.models import OpeningPhoto

    assert newsletter.id is not None
    opening = openings.add(
        conn,
        Opening(
            newsletter_id=newsletter.id,
            brand_name="Wycon",
            location="Lyon",
            opening_date=date(2026, 10, 1),
        ),
    )
    assert opening.id is not None
    for name in ("2026-10/a.jpg", "2026-10/b.jpg"):
        openings.add_photo(conn, OpeningPhoto(opening_id=opening.id, file_name=name))
    view = build_newsletter_view(conn, "2026-10", settings)
    item = view.sections[2].items[0]
    assert item.main_photo.file_name == "2026-10/a.jpg"
    assert [p.file_name for p in item.other_photos] == ["2026-10/b.jpg"]
    assert item.date_label == "1er octobre 2026"


# --------------------------------------------------------------------------- QR codes


def _matrix_from_svg(svg: str) -> list[list[bool]]:
    """Reconstruit la matrice à partir du chemin SVG (un carré par module noir)."""
    root = ET.fromstring(svg)
    size = int(root.get("viewBox", "").split()[2])
    matrix = [[False] * size for _ in range(size)]
    path = root.find(f"{SVG_NS}path")
    assert path is not None
    for x, y in re.findall(r"M(\d+) (\d+)h1v1h-1z", path.get("d", "")):
        matrix[int(y)][int(x)] = True
    return matrix


def test_qr_svg_is_valid_xml_and_matches_url(tmp_path: Path) -> None:
    url = "https://example.com/article?id=1&x=é"
    svg = qr.qr_svg(url)
    root = ET.fromstring(svg)
    assert root.tag == f"{SVG_NS}svg"
    assert _matrix_from_svg(svg) == qr.qr_matrix(url)
    assert _matrix_from_svg(svg) != qr.qr_matrix("https://example.com/autre")


def test_qr_cache_is_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://example.com/cache"
    first = qr.qr_svg(url, tmp_path)
    cached = tmp_path / f"{qr.url_digest(url)}.svg"
    assert cached.is_file()

    def fail(_: str) -> list[list[bool]]:
        raise AssertionError("le cache aurait dû être utilisé")

    monkeypatch.setattr(qr, "qr_matrix", fail)
    assert qr.qr_svg(url, tmp_path) == first


def test_qr_png_is_cached(tmp_path: Path) -> None:
    path = qr.qr_png("https://example.com/png", cache_dir=tmp_path)
    assert path.parent == tmp_path and path.suffix == ".png"
    mtime = path.stat().st_mtime_ns
    assert qr.qr_png("https://example.com/png", cache_dir=tmp_path) == path
    assert path.stat().st_mtime_ns == mtime
    with Image.open(path) as image:
        assert image.format == "PNG"


@pytest.mark.parametrize("url", ["javascript:alert(1)", "ftp://example.com/x", "", "/relatif"])
def test_qr_refuses_non_http_links(url: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        qr.qr_svg(url)
    with pytest.raises(ValueError):
        qr.qr_png(url, cache_dir=tmp_path)


# --------------------------------------------------------------------------- aperçu


@pytest.fixture
def demo_client(client: FlaskClient, settings: Settings) -> FlaskClient:
    assert demo.main([], settings=settings, out=lambda _: None) == 0
    return client


def test_preview_of_demo_month(demo_client: FlaskClient, settings: Settings) -> None:
    response = demo_client.get("/newsletters/2000-01/apercu")
    assert response.status_code == 200
    html = _html(response)
    for title in (
        "À la une ce mois-ci",
        "Marché de la franchise",
        "Nos enseignes",
        "Ouvertures du mois",
        "Enseignes rencontrées",
        "Plans de développement",
    ):
        assert title in html
    assert "Janvier 2000" in html
    # Charte : bandeau avec logo en réserve blanche et motif, logo couleur en pied de page,
    # rubriques numérotées sur deux chiffres (renumérotées sans trou).
    assert 'src="/theme/logo/blanc"' in html and 'src="/theme/logo"' in html
    assert 'class="nl-motif"' in html
    numbers = re.findall(r'class="nl-section-number">(\d+)<', html)
    assert numbers == ["01", "02", "03", "04", "05"]
    # Aucun franchisé validé dans la démo : rubrique masquée.
    assert 'id="rubrique-5"' not in html
    # Un QR code par article, juste sous son titre.
    titles = re.findall(r'nl-article-title"><a href="([^"]+)"', html)
    assert len(titles) == 13
    assert html.count('class="qr"') == len(titles)
    assert "Opportunité emplacements" in html
    # Photos principales servies par l'application.
    assert html.count('<figure class="nl-photo">') == 2
    # Pokawa a 2 photos : la seconde en vignette.
    assert html.count('<div class="nl-thumbs">') == 1
    assert "/photos/2000-01/" in html
    # QR codes mis en cache dans <données>/exports/qr.
    assert len(list((settings.exports_dir / "qr").glob("*.svg"))) == 13


def test_preview_qr_follows_its_article(demo_client: FlaskClient) -> None:
    html = _html(demo_client.get("/newsletters/2000-01/apercu"))
    pairs = re.findall(
        r'nl-article-title"><a href="([^"]+)".*?<div class="nl-qr">(<svg.*?</svg>)',
        html,
        flags=re.DOTALL,
    )
    assert len(pairs) == 13
    for url, svg in pairs:
        assert _matrix_from_svg(svg) == qr.qr_matrix(url.replace("&amp;", "&"))


def test_preview_escapes_titles(demo_client: FlaskClient) -> None:
    html = _html(demo_client.get("/newsletters/2000-01/apercu"))
    assert "&lt;script&gt;alert(" in html
    assert "<script>alert" not in html


def test_preview_unknown_or_invalid_month_is_404(client: FlaskClient) -> None:
    assert client.get("/newsletters/2099-01/apercu").status_code == 404
    assert client.get("/newsletters/2099-13/apercu").status_code == 404


def test_preview_of_empty_month_explains(client: FlaskClient, newsletter: Newsletter) -> None:
    response = client.get("/newsletters/2026-10/apercu")
    assert response.status_code == 200
    assert "encore vide" in _html(response)


def test_preview_button_on_month_screen(demo_client: FlaskClient) -> None:
    html = _html(demo_client.get("/newsletters/2000-01/rubrique-1"))
    assert 'href="/newsletters/2000-01/apercu"' in html


def test_preview_with_invalid_theme(app: Flask, demo_client: FlaskClient, tmp_path: Path) -> None:
    app.config["NF_THEME_FILE"] = write_theme(tmp_path, **{"colors.text": "rouge"})
    response = demo_client.get("/newsletters/2000-01/apercu")
    assert response.status_code == 500
    assert "colors.text" in _html(response)


# --------------------------------------------------------------------------- écran Thème


def test_theme_screen(client: FlaskClient) -> None:
    html = _html(client.get("/theme"))
    assert "#EF4050" in html and "Century Gothic" in html and "Bahnschrift" in html
    assert "minimum" in html.lower()
    assert client.get("/theme/logo/blanc").status_code == 200
    assert client.get("/theme/logo/autre").status_code == 404
    assert "Tous les contrastes vérifiés" in html
    assert "theme.yaml" in html
    assert client.get("/theme/logo").status_code == 200
    assert 'href="/theme"' in _html(client.get("/"))


def test_theme_screen_shows_warning_and_errors(
    app: Flask, client: FlaskClient, tmp_path: Path
) -> None:
    app.config["NF_THEME_FILE"] = write_theme(tmp_path, **{"colors.muted": "#777777"})
    html = _html(client.get("/theme"))
    assert "Contraste insuffisant" in html and "4,48:1" in html and "Insuffisant" in html

    app.config["NF_THEME_FILE"] = write_theme(tmp_path, logo="absent.png")
    response = client.get("/theme")
    assert response.status_code == 200
    assert "logo introuvable" in _html(response)
    assert client.get("/theme/logo").status_code == 404


def test_provisional_logo_is_generated(tmp_path: Path) -> None:
    from news_franchise.newsletter.theme import generate_provisional_logo

    path = generate_provisional_logo(tmp_path / "assets" / "logo.png")
    with Image.open(path) as image:
        assert image.format == "PNG" and image.size == (600, 120)


def test_system_font_falls_back_without_accents(monkeypatch: pytest.MonkeyPatch) -> None:
    from news_franchise import fonts

    monkeypatch.setattr(fonts, "FONT_CANDIDATES", ("introuvable.ttf",))
    text, _ = fonts.system_font(20, "DÉMO")
    assert text == "DMO"
    text, _ = fonts.system_font(20, "DÉMO", "DEMO")
    assert text == "DEMO"
