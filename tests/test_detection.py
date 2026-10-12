"""Tests de la détection : cas étiquetés, règles, enregistrement prudent, outils."""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

from news_franchise.brand_catalog import load_brand_catalog
from news_franchise.collect.matching import BrandMatcher
from news_franchise.config import Settings
from news_franchise.db.connection import MIGRATIONS_DIR, current_version, get_connection, init_db
from news_franchise.detect.franchisee import FranchiseeExtractor
from news_franchise.detect.opportunity import OpportunityDetector
from news_franchise.detect.places import PlaceMatcher
from news_franchise.detect.rules import (
    DETECTION_RULES_FILE,
    DetectionRulesError,
    load_detection_rules,
    load_places,
)
from news_franchise.detect.runner import run_detection
from news_franchise.detect.text import split_sentences
from news_franchise.models import Article, Brand, Franchisee, Newsletter
from news_franchise.repositories import articles, brands, franchisees
from news_franchise.tools import detect as detect_tool
from news_franchise.tools import evaluate_detection
from tests.helpers import FIXTURES_DIR, post_form, web_app

CASES = yaml.safe_load((FIXTURES_DIR / "detection_cases.yaml").read_text(encoding="utf-8"))["cases"]
NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def project_brands() -> list[Brand]:
    return [
        Brand(
            id=index,
            name=e.name,
            slug=str(index),
            sector=e.sector,
            aliases=list(e.aliases),
            case_sensitive=e.case_sensitive,
        )
        for index, e in enumerate(load_brand_catalog(), start=1)
    ]


@pytest.fixture(scope="module")
def detectors(project_brands: list[Brand]) -> tuple[OpportunityDetector, FranchiseeExtractor]:
    rules = load_detection_rules()
    extractor = FranchiseeExtractor(
        rules.franchisee, PlaceMatcher(load_places()), BrandMatcher(project_brands)
    )
    return OpportunityDetector(rules.opportunity), extractor


# --------------------------------------------------------------------------- cas étiquetés


def test_at_least_15_labelled_cases() -> None:
    assert len(CASES) >= 15
    assert len({case["id"] for case in CASES}) == len(CASES)


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_labelled_case(
    case: dict[str, Any],
    detectors: tuple[OpportunityDetector, FranchiseeExtractor],
    project_brands: list[Brand],
) -> None:
    opportunity, extractor = detectors
    sentences = split_sentences(case["text"])
    article_brand = next((b for b in project_brands if b.name == case.get("article_brand")), None)

    match = opportunity.detect(sentences)
    assert (match is not None) == case.get("opportunity", False)
    if match:
        assert match.sentence in case["text"] and match.terms

    found, unnamed = extractor.extract(sentences, article_brand)
    assert len(unnamed) == case.get("unnamed", 0)
    expected = case.get("franchisee")
    if expected is None:
        assert found == []
        return
    assert len(found) == 1
    candidate = found[0]
    assert candidate.name == expected["name"]
    assert candidate.brands == expected["brands"]
    assert candidate.location == expected["location"]
    assert candidate.store_count == expected["store_count"]
    assert candidate.confidence == expected["confidence"]
    assert candidate.evidence in case["text"] and candidate.trigger_terms


@pytest.mark.parametrize(
    ("sentence", "count"),
    [
        ("Il exploite cinq restaurants.", 5),
        ("Elle possède douze magasins.", 12),
        ("Le réseau compte 48 points de vente.", 48),
        ("Ils gèrent trois unités et deux établissements.", 3),
        ("Il exploite des restaurants.", None),
        ("En 2026, l'enseigne a grandi.", None),
    ],
)
def test_store_count(
    sentence: str, count: int | None, detectors: tuple[OpportunityDetector, FranchiseeExtractor]
) -> None:
    assert detectors[1].store_count(sentence) == count


# --------------------------------------------------------------------------- base de données


@pytest.fixture
def db(conn: sqlite3.Connection) -> sqlite3.Connection:
    brands.sync_from_yaml(conn)
    return conn


def _article(
    conn: sqlite3.Connection, newsletter: Newsletter, url: str, title: str, body: str = ""
) -> Article:
    assert newsletter.id is not None
    added = articles.add(
        conn,
        Article(
            newsletter_id=newsletter.id,
            rubric=1,
            title=title,
            source_name="Toute la Franchise",
            url=url,
            body_text=body or None,
        ),
    )
    assert added is not None
    return added


def test_detection_saves_evidence_and_source(
    db: sqlite3.Connection, newsletter: Newsletter
) -> None:
    opp = _article(
        db,
        newsletter,
        "https://a.example/opp",
        "Pokawa accélère",
        "L'enseigne se porte bien. Pokawa recherche des emplacements en centre commercial.",
    )
    other = _article(db, newsletter, "https://a.example/rien", "Météo du week-end", "Il fera beau.")
    fra = _article(
        db,
        newsletter,
        "https://b.example/franchise",
        "Un multi-franchisé en vue",
        "Jean Dupont, multi-franchisé O'Tacos à la tête de cinq restaurants en Occitanie.",
    )

    report = run_detection(db, "2026-10")

    assert len(report.opportunities) == 1 and report.by_confidence["haute"] == 1
    saved = articles.get(db, opp.id)  # type: ignore[arg-type]
    assert saved is not None and saved.is_opportunity and saved.opportunity_source == "auto"
    assert saved.opportunity_evidence == "Pokawa recherche des emplacements en centre commercial."
    assert saved.opportunity_terms == ["recherche des emplacements en centre commercial"]
    untouched = articles.get(db, other.id)  # type: ignore[arg-type]
    assert (
        untouched is not None and not untouched.is_opportunity and untouched.opportunity_terms == []
    )

    [fiche] = franchisees.list_for_newsletter(db, newsletter.id)  # type: ignore[arg-type]
    assert fiche.name == "Jean Dupont" and fiche.brands == "O'Tacos"
    assert fiche.location == "Occitanie" and fiche.store_count == 5
    assert fiche.confidence == "haute" and fiche.validated is False
    assert fiche.source_url == fra.url and fiche.source_name == "Toute la Franchise"
    assert fiche.article_id == fra.id
    assert fiche.evidence is not None and fiche.evidence.startswith("Jean Dupont")
    assert "multi-franchisé" in fiche.trigger_terms


def test_duplicate_in_month_is_merged(db: sqlite3.Connection, newsletter: Newsletter) -> None:
    first = _article(
        db,
        newsletter,
        "https://a.example/1",
        "Portrait",
        "Jean Dupont, multi-franchisé O'Tacos, s'installe à Toulouse.",
    )
    _article(
        db,
        newsletter,
        "https://b.example/2",
        "Suite",
        "Jean DUPONT est désormais à la tête de 6 restaurants.",
    )
    run_detection(db, "2026-10")
    [fiche] = franchisees.list_for_newsletter(db, newsletter.id)  # type: ignore[arg-type]
    assert fiche.location == "Toulouse" and fiche.store_count == 6  # complétée
    assert fiche.source_url == first.url  # première source conservée
    assert fiche.confidence == "haute"


def test_rerun_never_touches_user_work(db: sqlite3.Connection, newsletter: Newsletter) -> None:
    nid = newsletter.id
    assert nid is not None
    opp = _article(
        db,
        newsletter,
        "https://a.example/o",
        "Pokawa recherche des emplacements en centre commercial",
    )
    _article(
        db,
        newsletter,
        "https://a.example/f",
        "Portraits",
        "Jean Dupont, multi-franchisé O'Tacos à Lyon. "
        "Selon Marie Durand, franchisée de Pokawa à Nice, tout va bien. "
        "Paul Martin, multi-franchisé Wycon, exploite 3 boutiques. "
        "Anne Petit, multi-franchisée Leonidas, vise Reims.",
    )
    run_detection(db, "2026-10")
    by_name = {f.name: f for f in franchisees.list_for_newsletter(db, nid)}
    assert set(by_name) == {"Jean Dupont", "Marie Durand", "Paul Martin", "Anne Petit"}

    # Travail de l'utilisateur.
    articles.set_opportunity(db, opp.id, False)  # type: ignore[arg-type]
    franchisees.set_validated(db, by_name["Jean Dupont"].id, True)  # type: ignore[arg-type]
    edited = by_name["Marie Durand"]
    edited.location = "Nice et Cannes"
    franchisees.update(db, edited)
    franchisees.set_dismissed(db, by_name["Paul Martin"].id, True)  # type: ignore[arg-type]
    before = {f.id: f for f in franchisees.list_for_newsletter(db, nid, include_dismissed=True)}
    opp_before = articles.get(db, opp.id)  # type: ignore[arg-type]

    report = run_detection(db, "2026-10")

    assert articles.get(db, opp.id) == opp_before  # type: ignore[arg-type]
    assert opp_before is not None and not opp_before.is_opportunity
    assert opp_before.opportunity_source == "manual"
    assert report.protected_opportunities == 1 and report.protected_franchisees == 3
    after = {f.id: f for f in franchisees.list_for_newsletter(db, nid, include_dismissed=True)}
    for name in ("Jean Dupont", "Marie Durand", "Paul Martin"):
        fiche_id = by_name[name].id
        assert after[fiche_id] == before[fiche_id], name
    assert after[by_name["Marie Durand"].id].location == "Nice et Cannes"
    assert after[by_name["Paul Martin"].id].dismissed  # écartée : jamais recréée
    assert len(after) == 4


def test_stale_suggestion_removed_but_validated_kept(
    db: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _article(
        db,
        newsletter,
        "https://a.example/f",
        "Portraits",
        "Jean Dupont, multi-franchisé O'Tacos à Lyon. Anne Petit, multi-franchisée Leonidas.",
    )
    run_detection(db, "2026-10")
    by_name = {f.name: f for f in franchisees.list_for_newsletter(db, newsletter.id)}  # type: ignore[arg-type]
    franchisees.set_validated(db, by_name["Anne Petit"].id, True)  # type: ignore[arg-type]
    article.body_text = "Article réécrit sans franchisé."
    articles.update(db, article)

    report = run_detection(db, "2026-10")

    assert report.suggestions_removed == 1
    names = [f.name for f in franchisees.list_for_newsletter(db, newsletter.id)]  # type: ignore[arg-type]
    assert names == ["Anne Petit"]


def test_manual_franchisee_and_manual_opportunity_via_update(
    db: sqlite3.Connection, newsletter: Newsletter
) -> None:
    assert newsletter.id is not None
    article = _article(db, newsletter, "https://a.example/x", "Un article ordinaire")
    article.is_opportunity = True
    saved = articles.update(db, article)
    assert saved.opportunity_source == "manual"
    manual = franchisees.add(
        db,
        Franchisee(
            newsletter_id=newsletter.id,
            name="Jean Dupont",
            source_name="Saisie",
            source_url="https://a.example/x",
        ),
    )
    _article(db, newsletter, "https://a.example/y", "Jean Dupont, multi-franchisé O'Tacos")
    run_detection(db, "2026-10")
    assert articles.get(db, article.id).is_opportunity  # type: ignore[union-attr, arg-type]
    assert franchisees.get(db, manual.id) == manual  # type: ignore[arg-type]


def test_invalid_rules_change_nothing(
    db: sqlite3.Connection, newsletter: Newsletter, tmp_path: Path
) -> None:
    article = _article(
        db,
        newsletter,
        "https://a.example/o",
        "Pokawa recherche des emplacements en centre commercial",
    )
    bad = tmp_path / "regles.yaml"
    text = DETECTION_RULES_FILE.read_text(encoding="utf-8")
    bad.write_text(
        text.replace('    - "à la tête de {n}"', '    - "à la tête de ({n}"'), encoding="utf-8"
    )
    with pytest.raises(DetectionRulesError, match=r"« à la tête de \(\{n\} » .* invalide"):
        run_detection(db, "2026-10", rules_path=bad)
    bad.write_text("opportunity:\n  search_terms: []\n", encoding="utf-8")
    with pytest.raises(DetectionRulesError, match="search_terms"):
        run_detection(db, "2026-10", rules_path=bad)
    saved = articles.get(db, article.id)  # type: ignore[arg-type]
    assert saved is not None and saved.opportunity_source is None and not saved.is_opportunity
    assert franchisees.list_for_newsletter(db, newsletter.id) == []  # type: ignore[arg-type]


def test_yaml_boolean_trap_is_explained(tmp_path: Path) -> None:
    bad = tmp_path / "regles.yaml"
    text = DETECTION_RULES_FILE.read_text(encoding="utf-8").replace('    - "On"', "    - On")
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(DetectionRulesError, match="entre guillemets"):
        load_detection_rules(bad)


def test_migration_0004_keeps_data(settings: Settings, tmp_path: Path) -> None:
    previous = tmp_path / "migrations_v3"
    previous.mkdir()
    for name in ("0001_initial.sql", "0002_article_body.sql", "0003_brand_case_sensitive.sql"):
        shutil.copy(MIGRATIONS_DIR / name, previous)
    assert init_db(settings, previous) == 3
    with closing(get_connection(settings)) as conn:
        conn.execute(
            "INSERT INTO newsletters (id, month, created_at, updated_at)"
            " VALUES (1, '2026-10', '2026-10-01T00:00:00+00:00', '2026-10-01T00:00:00+00:00')"
        )
        conn.execute(
            "INSERT INTO articles (id, newsletter_id, rubric, title, source_name, url,"
            " is_opportunity, position, collected_at, body_text)"
            " VALUES (1, 1, 2, 'Titre', 'Source', 'https://a.example/1', 1, 3,"
            " '2026-10-02T00:00:00+00:00', 'Texte de l''article')"
        )
        conn.execute(
            "INSERT INTO franchisees (newsletter_id, name, source_name, source_url, validated)"
            " VALUES (1, 'Jean Dupont', 'Source', 'https://a.example/1', 1)"
        )
    assert init_db(settings) >= 4
    with closing(get_connection(settings)) as conn:
        assert current_version(conn) >= 4
        article = articles.get(conn, 1)
        assert article is not None and article.is_opportunity and article.position == 3
        assert article.body_text == "Texte de l'article"
        assert article.opportunity_source is None and article.opportunity_terms == []
        [fiche] = franchisees.list_for_newsletter(conn, 1)
        assert fiche.validated and fiche.confidence is None and not fiche.edited
        assert fiche.trigger_terms == []


# --------------------------------------------------------------------------- outils


def test_detect_command(settings: Settings, db: sqlite3.Connection, newsletter: Newsletter) -> None:
    _article(
        db,
        newsletter,
        "https://a.example/o",
        "Pokawa recherche des emplacements en centre commercial",
    )
    output: list[str] = []
    code = detect_tool.main(["--month", "2026-10"], settings=settings, out=output.append)
    text = "\n".join(output)
    assert code == 0
    assert "Opportunités détectées             : 1" in text
    assert "Phrase : « Pokawa recherche des emplacements en centre commercial »" in text


def test_evaluation_report(
    settings: Settings, db: sqlite3.Connection, newsletter: Newsletter
) -> None:
    opp = _article(
        db,
        newsletter,
        "https://a.example/o",
        "Pokawa recherche des emplacements en centre commercial",
    )
    _article(
        db,
        newsletter,
        "https://a.example/miss",
        "Wycon prospecte",
        "Wycon prospecte de nouvelles villes. Elle aime les centres commerciaux.",
    )
    _article(
        db,
        newsletter,
        "https://a.example/f",
        "Portrait",
        "Jean Dupont, multi-franchisé O'Tacos à la tête de cinq restaurants en Occitanie.",
    )
    output: list[str] = []
    code = evaluate_detection.main(
        ["--month", "2026-10"], settings=settings, clock=lambda: NOW, out=output.append
    )
    assert code == 0
    [report_path] = settings.reports_dir.glob("detection-2026-10-*.md")
    text = report_path.read_text(encoding="utf-8")
    assert "## 1. Opportunités détectées (1)" in text
    assert f"]({opp.url})" in text
    assert "- [ ] juste  - [ ] faux" in text
    assert "## 4. Articles non marqués contenant un terme d'opportunité (1)" in text
    assert "Wycon prospecte" in text and "- [ ] oubli" in text
    assert "### F1. Jean Dupont — confiance haute" in text
    # Simulation : la base n'est pas modifiée.
    assert articles.get(db, opp.id).opportunity_source is None  # type: ignore[union-attr, arg-type]
    assert franchisees.list_for_newsletter(db, newsletter.id) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------- intégration


def test_collection_runs_detection(
    settings: Settings, db: sqlite3.Connection, fetcher: Any, mock_http: Any, tmp_path: Path
) -> None:
    from news_franchise.collect.runner import run_collection
    from news_franchise.repositories import collection_runs
    from tests.test_collect_runner import FEED_A, _site_routes, write_sources

    _site_routes(mock_http)
    sources = write_sources(tmp_path, [("Site A", FEED_A)])
    report = run_collection(
        db, settings, "2026-10", lambda: NOW, fetcher=fetcher, sources_path=sources
    )
    assert report.detection is not None and report.detection_error is None
    assert report.detection["articles_analysed"] == 3
    run = collection_runs.get(db, report.run_id)
    assert run is not None and run.stats["detection"] == report.detection

    # Règles invalides : la collecte reste valable, l'erreur est signalée.
    bad = tmp_path / "regles.yaml"
    bad.write_text("opportunity: {}\n", encoding="utf-8")
    second = run_collection(
        db,
        settings,
        "2026-10",
        lambda: NOW,
        fetcher=fetcher,
        sources_path=sources,
        detection_rules_path=bad,
    )
    assert second.status == "success"
    assert second.detection is None
    assert second.detection_error is not None and "Détection non lancée" in second.detection_error


def test_web_detection_button(
    settings: Settings, db: sqlite3.Connection, newsletter: Newsletter, tmp_path: Path
) -> None:
    _article(
        db,
        newsletter,
        "https://a.example/o",
        "Pokawa recherche des emplacements en centre commercial",
    )
    app = web_app(settings)
    app.config["NF_CLOCK"] = lambda: NOW
    client = app.test_client()
    assert "Relancer la détection" in client.get("/collecte/").get_data(as_text=True)

    response = post_form(client, "/collecte/detection", {"mois": "2026-10"})
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Opportunités détectées</th><td>1" in html
    assert "Pokawa recherche des emplacements en centre commercial" in html

    bad = tmp_path / "regles.yaml"
    bad.write_text("franchisee: []\n", encoding="utf-8")
    app.config["NF_DETECTION_RULES_FILE"] = bad
    response = post_form(client, "/collecte/detection", {"mois": "2026-10"})
    assert response.status_code == 400
    assert "regles.yaml" in response.get_data(as_text=True)
