"""Outils partagés par les tests (données de référence et simulation HTTP)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Date « aujourd'hui » injectée dans les évaluations (pas d'horloge réelle).
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)

RSS_HEADERS = {"content-type": "application/rss+xml; charset=utf-8"}
HTML_HEADERS = {"content-type": "text/html; charset=utf-8"}


def fixture_bytes(name: str) -> bytes:
    """Contenu brut d'un fichier de tests/fixtures."""
    return (FIXTURES_DIR / name).read_bytes()


def rss(name: str) -> httpx.Response:
    """Réponse 200 contenant le flux RSS de la fixture donnée."""
    return httpx.Response(200, content=fixture_bytes(name), headers=RSS_HEADERS)


def html(name: str) -> httpx.Response:
    """Réponse 200 contenant la page HTML de la fixture donnée."""
    return httpx.Response(200, content=fixture_bytes(name), headers=HTML_HEADERS)


def serve(
    router: respx.MockRouter,
    routes: Mapping[str, object],
    fallback: httpx.Response | None = None,
) -> dict[str, respx.Route]:
    """Déclare des routes GET simulées, puis une route de repli (404 par défaut).

    Chaque valeur est une httpx.Response, ou un effet de bord respx (liste de
    réponses successives, exception, fonction).
    """
    created: dict[str, respx.Route] = {}
    for url, outcome in routes.items():
        route = router.get(url)
        if isinstance(outcome, httpx.Response):
            route.mock(return_value=outcome)
        else:
            route.mock(side_effect=outcome)
        created[url] = route
    router.route().mock(return_value=fallback or httpx.Response(404))
    return created
