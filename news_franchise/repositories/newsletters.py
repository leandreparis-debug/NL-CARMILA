"""Dépôt des newsletters (une par mois) et calcul des chiffres de la Une."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from news_franchise.db.connection import transaction
from news_franchise.models import (
    NEWSLETTER_STATUSES,
    FrontPageFigures,
    Newsletter,
    validate_month,
    validate_url,
)
from news_franchise.repositories import openings
from news_franchise.repositories._common import (
    from_iso_datetime,
    to_iso_datetime,
    utcnow,
)

_COLUMNS = (
    "id, month, status, development_plans_url, development_plans_label, created_at, updated_at"
)


def _from_row(row: sqlite3.Row) -> Newsletter:
    """Ligne SQL → Newsletter."""
    return Newsletter(
        id=row["id"],
        month=row["month"],
        status=row["status"],
        development_plans_url=row["development_plans_url"],
        development_plans_label=row["development_plans_label"],
        created_at=from_iso_datetime(row["created_at"]),
        updated_at=from_iso_datetime(row["updated_at"]),
    )


def get(conn: sqlite3.Connection, month: str) -> Newsletter | None:
    """Newsletter du mois AAAA-MM, ou None si elle n'existe pas. ValueError si mois invalide."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM newsletters WHERE month = ?", (validate_month(month),)
    ).fetchone()
    return _from_row(row) if row else None


def get_by_id(conn: sqlite3.Connection, newsletter_id: int) -> Newsletter | None:
    """Newsletter par identifiant, ou None."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM newsletters WHERE id = ?", (newsletter_id,)
    ).fetchone()
    return _from_row(row) if row else None


def get_or_create(conn: sqlite3.Connection, month: str) -> Newsletter:
    """Renvoie la newsletter du mois, en la créant (statut draft) si besoin. Idempotent."""
    month = validate_month(month)
    now = to_iso_datetime(utcnow())
    conn.execute(
        "INSERT INTO newsletters (month, created_at, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT (month) DO NOTHING",
        (month, now, now),
    )
    newsletter = get(conn, month)
    assert newsletter is not None
    return newsletter


def list_all(conn: sqlite3.Connection) -> list[Newsletter]:
    """Historique des newsletters, de la plus récente à la plus ancienne."""
    rows = conn.execute(f"SELECT {_COLUMNS} FROM newsletters ORDER BY month DESC")
    return [_from_row(row) for row in rows]


def _touch_update(
    conn: sqlite3.Connection, newsletter_id: int, column: str, value: object
) -> Newsletter:
    """Met à jour une colonne (nom fixé dans le code) et updated_at ; renvoie la newsletter."""
    assert column in ("status", "development_plans_url", "development_plans_label")
    cursor = conn.execute(
        f"UPDATE newsletters SET {column} = ?, updated_at = ? WHERE id = ?",
        (value, to_iso_datetime(utcnow()), newsletter_id),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"Newsletter introuvable (id {newsletter_id}).")
    newsletter = get_by_id(conn, newsletter_id)
    assert newsletter is not None
    return newsletter


def set_status(conn: sqlite3.Connection, newsletter_id: int, status: str) -> Newsletter:
    """Change le statut (draft, reviewed, exported). ValueError si statut inconnu."""
    if status not in NEWSLETTER_STATUSES:
        raise ValueError(
            f"Statut de newsletter invalide : {status!r} "
            f"(attendu : {', '.join(NEWSLETTER_STATUSES)})."
        )
    return _touch_update(conn, newsletter_id, "status", status)


def set_development_plans_url(
    conn: sqlite3.Connection, newsletter_id: int, url: str | None
) -> Newsletter:
    """Enregistre (ou efface avec None / « ») le lien vers les plans de développement."""
    value = validate_url(url, "development_plans_url") if url and url.strip() else None
    return _touch_update(conn, newsletter_id, "development_plans_url", value)


def set_development_plans(
    conn: sqlite3.Connection, newsletter_id: int, url: str | None, label: str | None
) -> Newsletter:
    """Enregistre le lien des plans de développement et son libellé (None = défaut).

    Seul le format est vérifié (http/https) : le lien, souvent interne (SharePoint,
    Google Drive), n'est jamais appelé. url None ou vide retire le lien et le libellé.
    """
    if not url or not url.strip():
        set_development_plans_url(conn, newsletter_id, None)
        return _touch_update(conn, newsletter_id, "development_plans_label", None)
    if label is not None and len(label) > 100:
        raise ValueError("Le libellé du lien est trop long (100 caractères au plus).")
    set_development_plans_url(conn, newsletter_id, url)
    return _touch_update(conn, newsletter_id, "development_plans_label", label or None)


def delete(conn: sqlite3.Connection, newsletter_id: int, photos_dir: Path | None = None) -> None:
    """Supprime une newsletter et, en cascade, tout son contenu.

    Si photos_dir est donné, les fichiers des photos d'ouverture sont aussi supprimés.
    """
    with transaction(conn):
        file_names = [
            row["file_name"]
            for row in conn.execute(
                "SELECT p.file_name FROM opening_photos p "
                "JOIN openings o ON o.id = p.opening_id WHERE o.newsletter_id = ?",
                (newsletter_id,),
            )
        ]
        conn.execute("DELETE FROM newsletters WHERE id = ?", (newsletter_id,))
    if photos_dir is not None:
        for file_name in file_names:
            openings.remove_photo_file(photos_dir, file_name)


def front_page_figures(conn: sqlite3.Connection, newsletter_id: int) -> FrontPageFigures:
    """Chiffres de la Une, calculés à la volée : ouvertures, enseignes rencontrées
    (noms distincts) et franchisés validés."""
    row = conn.execute(
        "SELECT"
        " (SELECT COUNT(*) FROM openings WHERE newsletter_id = :id) AS openings,"
        " (SELECT COUNT(DISTINCT lower(trim(brand_name))) FROM meetings"
        "   WHERE newsletter_id = :id) AS brands_met,"
        " (SELECT COUNT(*) FROM franchisees WHERE newsletter_id = :id AND validated = 1"
        " AND dismissed = 0)"
        "   AS franchisees",
        {"id": newsletter_id},
    ).fetchone()
    return FrontPageFigures(
        openings=row["openings"], brands_met=row["brands_met"], franchisees=row["franchisees"]
    )
