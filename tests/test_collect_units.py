"""Tests unitaires du collecteur : texte, URL, périodes, enseignes, classement, extraits."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import feedparser
import pytest

from news_franchise.brand_catalog import BRANDS_FILE, load_brand_catalog
from news_franchise.collect.config import (
    RULES_FILE,
    RulesConfigError,
    SourcesConfigError,
    load_rules,
    load_sources,
)
from news_franchise.collect.excerpt import PageContent, choose_excerpt, extract_page
from news_franchise.collect.feeds import parse_google_entry, split_google_title
from news_franchise.collect.matching import BrandMatcher, TermMatcher, classify
from news_franchise.collect.periods import in_month, month_of, previous_month
from news_franchise.collect.text import html_to_text, truncate_excerpt
from news_franchise.collect.urls import clean_url, url_key
from news_franchise.models import Brand
from tests.helpers import FIXTURES_DIR, fixture_bytes

COLLECT_FIXTURES = FIXTURES_DIR / "collect"


@pytest.fixture(scope="module")
def project_brands() -> list[Brand]:
    """Les 15 enseignes de config/enseignes.yaml, comme en base."""
    return [
        Brand(
            id=index,
            name=entry.name,
            slug=str(index),
            sector=entry.sector,
            aliases=list(entry.aliases),
            case_sensitive=entry.case_sensitive,
        )
        for index, entry in enumerate(load_brand_catalog(BRANDS_FILE), start=1)
    ]


@pytest.fixture(scope="module")
def matcher(project_brands: list[Brand]) -> BrandMatcher:
    return BrandMatcher(project_brands)


@pytest.fixture(scope="module")
def rules() -> tuple[TermMatcher, TermMatcher]:
    loaded = load_rules(RULES_FILE)
    return TermMatcher(loaded.development_terms), TermMatcher(loaded.exclusions)


# --------------------------------------------------------------------------- enseignes


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("O’Tacos ouvre à Lyon", "O'Tacos"),
        ("OTACOS recrute des franchisés", "O'Tacos"),
        ("Le succès d'O'Tacos", "O'Tacos"),
        ("Dunkin arrive à Marseille", "Dunkin' Donuts"),
        ("Dunkin’ Donuts ouvre", "Dunkin' Donuts"),
        ("Adopt ouvre 10 boutiques", "Adopt"),
        ("Une crêpe chez CREPE TOUCH", "Crêpe Touch"),
        ("Le Comptoir de Mathilde s'agrandit", "Comptoir de Mathilde"),
        ("adopter un chien", None),
        ("l'adoption d'un texte", None),
        ("Adoptez la bonne attitude", None),
        ("Les chopsticks sont prêtes", None),
    ],
)
def test_brand_detection(matcher: BrandMatcher, text: str, expected: str | None) -> None:
    found = matcher.find(text)
    assert (found.brand.name if found else None) == expected


def test_untracked_brand_is_ignored() -> None:
    brand = Brand(name="Pokawa", slug="pokawa", tracked=False)
    assert BrandMatcher([brand]).find("Pokawa ouvre") is None


# --------------------------------------------------------------------------- classement


def test_classification(matcher: BrandMatcher, rules: tuple[TermMatcher, TermMatcher]) -> None:
    development, exclusions = rules
    pokawa = classify("Pokawa ouvre son 100e restaurant", "", matcher, development, exclusions)
    assert pokawa is not None and pokawa.rubric == 2 and pokawa.brand is not None
    assert pokawa.brand.name == "Pokawa" and pokawa.brand.sector == "Restauration rapide"

    network = classify(
        "Un nouveau réseau de franchise dans la boulangerie", "", matcher, development, exclusions
    )
    assert network is not None and network.rubric == 1 and network.brand is None

    by_summary = classify(
        "Belle rentrée", "L'enseigne Wycon s'installe", matcher, development, exclusions
    )
    assert by_summary is not None and by_summary.rubric == 2

    assert (
        classify("La franchise d'assurance augmente", "", matcher, development, exclusions) is None
    )
    assert (
        classify("Franchise de TVA : ce qui change", "", matcher, development, exclusions) is None
    )
    assert classify("Météo : un week-end ensoleillé", "", matcher, development, exclusions) is None
    # Exclusion + vrai terme de développement : reste en rubrique 1.
    mixed = classify(
        "Franchise de TVA et réseau de franchise : le guide", "", matcher, development, exclusions
    )
    assert mixed is not None and mixed.rubric == 1


def test_development_terms_plural_and_accents() -> None:
    terms = TermMatcher(["franchisé", "s'implante", "points de vente"])
    assert terms.find("Les FRANCHISES du mois") is not None
    assert terms.find("L’enseigne s’implante à Nice") is not None
    assert terms.find("affranchissement postal") is None


# --------------------------------------------------------------------------- périodes


def test_paris_month_boundaries() -> None:
    paris_evening = datetime(2026, 10, 31, 22, 30, tzinfo=UTC)  # 23h30 à Paris (UTC+1)
    utc_evening = datetime(2026, 10, 31, 23, 30, tzinfo=UTC)  # 00h30 le 1er novembre à Paris
    assert in_month(paris_evening, "2026-10")
    assert month_of(utc_evening) == "2026-11"
    assert not in_month(utc_evening, "2026-10")


def test_previous_month() -> None:
    assert previous_month(datetime(2026, 11, 3, tzinfo=UTC)) == "2026-10"
    assert previous_month(datetime(2027, 1, 2, tzinfo=UTC)) == "2026-12"
    # 31/12 23h30 UTC = 1er janvier à Paris → mois précédent : décembre.
    assert previous_month(datetime(2026, 12, 31, 23, 30, tzinfo=UTC)) == "2026-12"


# --------------------------------------------------------------------------- URL


def test_url_normalization() -> None:
    a = "https://Site.example/articles/pokawa?utm_source=rss&utm_medium=feed&id=3#haut"
    assert clean_url(a) == "https://site.example/articles/pokawa?id=3"
    assert url_key(a) == url_key("https://site.example/articles/pokawa/?id=3&fbclid=x")
    assert url_key("https://www.a.example/x?gclid=1") == url_key("http://a.example/x/")
    assert url_key("https://a.example/x?page=2") != url_key("https://a.example/x?page=3")


# --------------------------------------------------------------------------- texte et extraits


def test_html_to_text_removes_markup() -> None:
    raw = "<p>Bonjour&nbsp;<b>tout</b>\n le   monde</p><script>alert(1)</script><style>p{}</style>"
    assert html_to_text(raw) == "Bonjour tout le monde"
    assert "<" not in html_to_text("&lt;script&gt;alert(1)&lt;/script&gt;")


def test_truncate_excerpt() -> None:
    sentence = "Première phrase assez longue pour compter dans la coupe du texte. "
    text = sentence * 10
    cut = truncate_excerpt(text, 300)
    assert len(cut) <= 301 and cut.endswith("…")
    assert cut.startswith("Première phrase")
    words = " ".join(["mot"] * 200)
    cut_words = truncate_excerpt(words, 300)
    assert cut_words.endswith("mot…") and len(cut_words) <= 301
    assert truncate_excerpt("Court.", 300) == "Court."


@pytest.mark.parametrize(
    ("fixture", "starts_with", "forbidden"),
    [
        (
            "article_cookies_menu.html",
            "L'enseigne de poke bowls Pokawa",
            ["cookies", "Partager", "injecté", "©"],
        ),
        (
            "article_main_sidebar.html",
            "Fondée à Nantes en 2019",
            ["newsletter", "plus lus", "droits"],
        ),
        (
            "article_wordpress.html",
            "La marque de parfums Adopt",
            ["cookies", "Accueil", "lire aussi", "commentaire"],
        ),
    ],
)
def test_extract_article_body(fixture: str, starts_with: str, forbidden: list[str]) -> None:
    page = extract_page((COLLECT_FIXTURES / fixture).read_text(encoding="utf-8"))
    assert page.body_text.startswith(starts_with)
    excerpt = choose_excerpt(page, "résumé du flux")
    assert excerpt.startswith(starts_with)
    assert len(excerpt) <= 301
    for text in (page.body_text, excerpt):
        assert "<" not in text
        for word in forbidden:
            assert word.lower() not in text.lower()


def test_excerpt_fallbacks() -> None:
    meta_only = extract_page(
        (COLLECT_FIXTURES / "article_meta_only.html").read_text(encoding="utf-8")
    )
    assert meta_only.body_text == ""
    assert choose_excerpt(meta_only, "résumé").startswith(
        "Reportage vidéo : la boulangerie Pain & Co"
    )
    assert choose_excerpt(None, "Résumé du flux RSS.") == "Résumé du flux RSS."
    assert choose_excerpt(PageContent("", ""), "") == ""


# --------------------------------------------------------------------------- Google Actualités


def test_google_title_suffix() -> None:
    assert split_google_title("O'Tacos ouvre à Lyon - Le Progrès", "Le Progrès") == (
        "O'Tacos ouvre à Lyon",
        "Le Progrès",
    )
    assert split_google_title("Titre - avec tiret - Ouest-France", None) == (
        "Titre - avec tiret",
        "Ouest-France",
    )
    assert split_google_title("Titre sans éditeur", None) == ("Titre sans éditeur", None)


def test_google_entry_parsing() -> None:
    parsed = feedparser.parse(fixture_bytes("google_news.xml"))
    entry = parse_google_entry(parsed.entries[0])
    assert entry is not None
    assert entry.title == "O'Tacos ouvre un restaurant à Lyon"
    assert entry.source_name == "Le Progrès"
    assert entry.link.startswith("https://news.google.com/rss/articles/")
    assert entry.published == datetime(2026, 10, 6, 7, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- configuration


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_sources_config(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "sources.yaml",
        "sources:\n"
        "  - {name: A, type: rss, url: 'https://a.example/feed', enabled: true}\n"
        "  - {name: B, type: rss, url: null, enabled: false, verdict: inexploitable}\n"
        "google_news:\n"
        "  enabled: true\n"
        "  query_template: '\"{brand}\" when:30d'\n"
        "  link_resolution: resolved\n"
        "  brands: [Pokawa]\n",
    )
    config = load_sources(path)
    assert [s.name for s in config.rss] == ["A"]
    assert config.google_news is not None and config.google_news.link_resolution == "resolved"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("sources:\n  - {name: A, type: rss, url: null, enabled: true}\n", "sans adresse de flux"),
        ("sources:\n  - {name: A, url: 'https://a.example', enabled: oui}\n", "true ou false"),
        ("google_news: {enabled: true, query_template: 'sans marque'}\n", "{brand}"),
        ("sources: []\n", "aucune source activée"),
    ],
)
def test_invalid_sources_config(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(SourcesConfigError, match=message.replace("{", r"\{").replace("}", r"\}")):
        load_sources(_write(tmp_path, "sources.yaml", text))


def test_missing_sources_config_explains_how_to_create(tmp_path: Path) -> None:
    with pytest.raises(SourcesConfigError, match="sources.proposed.yaml"):
        load_sources(tmp_path / "sources.yaml")


def test_rules_config(tmp_path: Path) -> None:
    assert "franchise" in load_rules().development_terms
    with pytest.raises(RulesConfigError, match="en double"):
        load_rules(_write(tmp_path, "r.yaml", "development_terms: [franchise, Franchise]\n"))
    with pytest.raises(RulesConfigError, match="clé"):
        load_rules(_write(tmp_path, "r.yaml", "development_terms: [a]\nexclusion: [b]\n"))
