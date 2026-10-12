"""Données d'affichage des onglets de contenu interne (Une, ouvertures, rencontres, plans)."""

from __future__ import annotations

import sqlite3
from typing import Any

from news_franchise.content import service
from news_franchise.models import DEFAULT_PLANS_LABEL, Newsletter
from news_franchise.repositories import brands, meetings, openings
from news_franchise.review.limits import Limits

CONTENT_TABS = ("une", "ouvertures", "rencontres", "plans")
TEMPLATES = {
    "une": "review/une.html",
    "ouvertures": "review/openings.html",
    "rencontres": "review/meetings.html",
    "plans": "review/plans.html",
}


def tab_context(
    conn: sqlite3.Connection, newsletter: Newsletter, tab: str, limits: Limits
) -> dict[str, Any]:
    """Variables propres à un onglet de contenu interne."""
    assert newsletter.id is not None
    if tab == "une":
        figures = service.front_page(conn, newsletter.id)
        return {"figures": figures, "plural": service.plural}
    if tab == "ouvertures":
        items = openings.list_for_newsletter(conn, newsletter.id)
        return {
            "items": items,
            "photos": {o.id: openings.list_photos(conn, o.id) for o in items},  # type: ignore[arg-type]
            "positions": {o.id: i for i, o in enumerate(items)},
            "total": len(items),
            "count": len(items),
            "limit": limits.ouvertures,
            "max_photos": limits.photos_par_ouverture,
            "brand_list": brands.list_all(conn, tracked_only=True),
            "date_value": service.opening_date_value,
        }
    if tab == "rencontres":
        items = meetings.list_for_newsletter(conn, newsletter.id)
        return {
            "items": items,
            "positions": {m.id: i for i, m in enumerate(items)},
            "total": len(items),
            "brand_list": brands.list_all(conn, tracked_only=True),
            "date_value": service.opening_date_value,
        }
    return {"default_plans_label": DEFAULT_PLANS_LABEL}
