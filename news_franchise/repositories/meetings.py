"""Dépôt des enseignes rencontrées (rubrique 4)."""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Sequence

from news_franchise.db.connection import transaction
from news_franchise.models import Meeting
from news_franchise.repositories import _common
from news_franchise.repositories._common import from_iso_date, to_iso_date

_COLUMNS = "id, newsletter_id, brand_name, meeting_date, comment, position"
_SCOPE = "newsletter_id = ?"


def _from_row(row: sqlite3.Row) -> Meeting:
    """Ligne SQL → Meeting."""
    return Meeting(
        id=row["id"],
        newsletter_id=row["newsletter_id"],
        brand_name=row["brand_name"],
        meeting_date=from_iso_date(row["meeting_date"]),
        comment=row["comment"],
        position=row["position"],
    )


def get(conn: sqlite3.Connection, meeting_id: int) -> Meeting | None:
    """Rencontre par identifiant, ou None."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    return _from_row(row) if row else None


def add(conn: sqlite3.Connection, meeting: Meeting) -> Meeting:
    """Ajoute une enseigne rencontrée (en fin de liste si position est None)."""
    item = dataclasses.replace(meeting)
    with transaction(conn):
        if item.position is None:
            item.position = _common.next_position(conn, "meetings", _SCOPE, (item.newsletter_id,))
        cursor = conn.execute(
            "INSERT INTO meetings (newsletter_id, brand_name, meeting_date, comment, position)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                item.newsletter_id,
                item.brand_name,
                to_iso_date(item.meeting_date),
                item.comment,
                item.position,
            ),
        )
        item.id = cursor.lastrowid
    return item


def list_for_newsletter(conn: sqlite3.Connection, newsletter_id: int) -> list[Meeting]:
    """Enseignes rencontrées d'une newsletter, dans l'ordre d'affichage."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM meetings WHERE {_SCOPE} ORDER BY position, id", (newsletter_id,)
    )
    return [_from_row(row) for row in rows]


def update(conn: sqlite3.Connection, meeting: Meeting) -> Meeting:
    """Enregistre les modifications d'une rencontre (LookupError si elle n'existe pas)."""
    meeting_id = _common.require_id(meeting.id, "Rencontre")
    item = dataclasses.replace(meeting)
    cursor = conn.execute(
        "UPDATE meetings SET newsletter_id = ?, brand_name = ?, meeting_date = ?, comment = ?,"
        " position = COALESCE(?, position) WHERE id = ?",
        (
            item.newsletter_id,
            item.brand_name,
            to_iso_date(item.meeting_date),
            item.comment,
            item.position,
            meeting_id,
        ),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"Rencontre introuvable (id {meeting_id}).")
    updated = get(conn, meeting_id)
    assert updated is not None
    return updated


def reorder(conn: sqlite3.Connection, newsletter_id: int, ordered_ids: Sequence[int]) -> None:
    """Fixe l'ordre d'affichage des rencontres (celles non citées suivent)."""
    _common.reorder(conn, "meetings", _SCOPE, (newsletter_id,), ordered_ids)


def delete(conn: sqlite3.Connection, meeting_id: int) -> None:
    """Supprime une rencontre."""
    conn.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,))
