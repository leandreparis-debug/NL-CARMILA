"""Test de bout en bout de l'outil de diagnostic (toutes les sources simulées)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from news_franchise.config import Settings
from news_franchise.http_client import Fetcher
from news_franchise.sources.candidates import CandidateSite
from news_franchise.sources.evaluation import build_google_news_url
from news_franchise.tools import diagnose_sources
from news_franchise.tools.diagnose_sources import main, select_targets
from tests.helpers import NOW, html, rss, serve

GOOD = CandidateSite("Franchise Test", "https://franchise-test.example")
FORBIDDEN = CandidateSite("Site Interdit", "https://forbidden.example")
CRASHING = CandidateSite("Site Qui Plante", "https://crash.example")
SITES = (GOOD, FORBIDDEN, CRASHING)
BRANDS = ("O'Tacos", "Wycon")


def _setup_routes(router: respx.MockRouter) -> None:
    router.get(url__startswith="https://franchise-test.example/articles/").mock(
        return_value=httpx.Response(200)
    )
    router.get(url__startswith="https://news.google.com/rss/articles/").mock(
        return_value=httpx.Response(200)
    )
    # Le site interdit refuse tout (403), y compris robots.txt.
    router.route(host="forbidden.example").mock(return_value=httpx.Response(403))
    # Un bug inattendu (exception non réseau) pendant le diagnostic d'un site.
    router.route(host="crash.example").mock(side_effect=RuntimeError("bug simulé"))
    serve(
        router,
        {
            "https://franchise-test.example/": html("site_with_link.html"),
            "https://franchise-test.example/actus/rss.xml": rss("rss_complete.xml"),
            build_google_news_url("O'Tacos"): rss("google_news.xml"),
            build_google_news_url("Wycon"): rss("google_news_empty.xml"),
        },
    )


def _run(settings: Settings, fetcher: Fetcher, argv: list[str]) -> tuple[int, list[str]]:
    output: list[str] = []
    code = main(
        argv,
        settings=settings,
        fetcher=fetcher,
        now=NOW,
        sites=SITES,
        brands=BRANDS,
        progress=output.append,
    )
    return code, output


def test_full_diagnosis_writes_reports(
    mock_http: respx.MockRouter, fetcher: Fetcher, settings: Settings, tmp_path: Path
) -> None:
    _setup_routes(mock_http)

    code, output = _run(settings, fetcher, [])

    assert code == 0
    reports_dir = settings.reports_dir
    assert reports_dir.is_relative_to(tmp_path)
    stamp = NOW.astimezone().strftime("%Y%m%d-%H%M")
    md_path = reports_dir / f"sources-{stamp}.md"
    json_path = reports_dir / f"sources-{stamp}.json"
    proposal_path = reports_dir / "sources.proposed.yaml"
    assert md_path.is_file() and json_path.is_file() and proposal_path.is_file()

    markdown = md_path.read_text(encoding="utf-8")
    assert "## Synthèse" in markdown
    assert "| Franchise Test | rss | **exploitable** |" in markdown
    assert "Le site a refusé l'accès (HTTP 403)" in markdown
    assert "| Site Qui Plante | rss | **inexploitable** |" in markdown
    assert "Erreur inattendue pendant le diagnostic (RuntimeError)" in markdown
    assert "Google Actualités" in markdown and "Le Progrès (2)" in markdown

    data = json.loads(json_path.read_text(encoding="utf-8"))
    by_name = {s["name"]: s for s in data["sources"]}
    assert by_name["Franchise Test"]["verdict"] == "exploitable"
    assert by_name["Site Interdit"]["verdict"] == "inexploitable"
    assert "HTTP 403" in by_name["Site Interdit"]["reason"]
    assert by_name["Google Actualités"]["verdict"] == "exploitable"

    proposal = yaml.safe_load(proposal_path.read_text(encoding="utf-8"))
    sources = {s["name"]: s for s in proposal["sources"]}
    assert sources["Franchise Test"] == {
        "name": "Franchise Test",
        "type": "rss",
        "url": "https://franchise-test.example/actus/rss.xml",
        "enabled": True,
        "verdict": "exploitable",
        "note": sources["Franchise Test"]["note"],
    }
    assert sources["Site Interdit"]["url"] is None
    assert sources["Site Interdit"]["enabled"] is False
    assert "HTTP 403" in sources["Site Interdit"]["note"]
    assert sources["Site Qui Plante"]["enabled"] is False
    google = proposal["google_news"]
    assert google["enabled"] is True
    assert google["query_template"] == '"{brand}" when:30d'
    assert google["link_resolution"] == "google_link_only"
    assert google["brands"] == list(BRANDS)

    assert any("Site Interdit" in line for line in output)
    # La trace de l'erreur inattendue est dans le journal, pas dans le rapport.
    log = (settings.logs_dir / "news_franchise.log").read_text(encoding="utf-8")
    assert "Traceback" in log and "bug simulé" in log
    assert "Traceback" not in markdown


def test_no_google_and_only(
    mock_http: respx.MockRouter, fetcher: Fetcher, settings: Settings
) -> None:
    _setup_routes(mock_http)
    code, _ = _run(settings, fetcher, ["--only", "franchise test"])
    assert code == 0
    proposal = yaml.safe_load(
        (settings.reports_dir / "sources.proposed.yaml").read_text(encoding="utf-8")
    )
    assert [s["name"] for s in proposal["sources"]] == ["Franchise Test"]
    assert "google_news" not in proposal


def test_select_targets() -> None:
    assert select_targets(None, True, SITES, BRANDS) == (list(SITES), [])
    assert select_targets("wycon", False, SITES, BRANDS) == ([], ["Wycon"])
    assert select_targets("Google", False, SITES, BRANDS) == ([], list(BRANDS))


def test_unknown_only_returns_error(settings: Settings, fetcher: Fetcher) -> None:
    code, _ = _run(settings, fetcher, ["--only", "inconnue"])
    assert code == 2


def test_tool_crash_returns_non_zero(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, fetcher: Fetcher
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("disque plein")

    monkeypatch.setattr(diagnose_sources, "write_reports", boom)
    code, _ = _run(settings, fetcher, ["--no-google", "--only", "Site Interdit"])
    assert code == 1
