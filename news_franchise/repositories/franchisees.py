"""Dépôt des franchisés identifiés (rubrique 5)."""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Sequence

from news_franchise.db.connection import transaction
from news_franchise.models import Franchisee
from news_franchise.repositories import _common

_COLUMNS = (
    "id, newsletter_id, name, brands, location, store_count, source_name, source_url,"
    " article_id, validated, position"
)
_SCOPE = "newsletter_id = ?"


def _from_row(row: sqlite3.Row) -> Franchisee:
    """Ligne SQL → Franchisee."""
    return Franchisee(
        id=row["id"],
        newsletter_id=row["newsletter_id"],
        name=row["name"],
        brands=row["brands"],
        location=row["location"],
        store_count=row["store_count"],
        source_name=row["source_name"],
        source_url=row["source_url"],
        article_id=row["article_id"],
        validated=bool(row["validated"]),
        position=row["position"],
    )


def _values(item: Franchisee) -> tuple[object, ...]:
    """Valeurs des colonnes modifiables, dans l'ordre de _COLUMNS (sans id)."""
    return (
        item.newsletter_id,
        item.name,
        item.brands,
        item.location,
        item.store_count,
        item.source_name,
        item.source_url,
        item.article_id,
        int(item.validated),
    )


def get(conn: sqlite3.Connection, franchisee_id: int) -> Franchisee | None:
    """Franchisé par identifiant, ou None."""
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM franchisees WHERE id = ?", (franchisee_id,)
    ).fetchone()
    return _from_row(row) if row else None


def add(conn: sqlite3.Connection, franchisee: Franchisee) -> Franchisee:
    """Ajoute un franchisé (en fin de liste si position est None) et le renvoie avec son id."""
    item = dataclasses.replace(franchisee)
    with transaction(conn):
        if item.position is None:
            item.position = _common.next_position(
                conn, "franchisees", _SCOPE, (item.newsletter_id,)
            )
        cursor = conn.execute(
            "INSERT INTO franchisees (newsletter_id, name, brands, location, store_count,"
            " source_name, source_url, article_id, validated, position)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*_values(item), item.position),
        )
        item.id = cursor.lastrowid
    return item


def list_for_newsletter(
    conn: sqlite3.Connection, newsletter_id: int, validated_only: bool = False
) -> list[Franchisee]:
    """Franchisés d'une newsletter dans l'ordre d'affichage ; validated_only pour n'avoir
    que ceux validés par l'utilisateur."""
    sql = f"SELECT {_COLUMNS} FROM franchisees WHERE {_SCOPE}"
    if validated_only:
        sql += " AND validated = 1"
    rows = conn.execute(sql + " ORDER BY position, id", (newsletter_id,))
    return [_from_row(row) for row in rows]


def update(conn: sqlite3.Connection, franchisee: Franchisee) -> Franchisee:
    """Enregistre les modifications d'un franchisé existant (LookupError s'il n'existe pas)."""
    franchisee_id = _common.require_id(franchisee.id, "Franchisé")
    item = dataclasses.replace(franchisee)
    cursor = conn.execute(
        "UPDATE franchisees SET newsletter_id = ?, name = ?, brands = ?, location = ?,"
        " store_count = ?, source_name = ?, source_url = ?, article_id = ?, validated = ?,"
        " position = COALESCE(?, position) WHERE id = ?",
        (*_values(item), item.position, franchisee_id),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"Franchisé introuvable (id {franchisee_id}).")
    updated = get(conn, franchisee_id)
    assert updated is not None
    return updated


def set_validated(conn: sqlite3.Connection, franchisee_id: int, validated: bool) -> None:
    """Valide (True) ou invalide (False) un franchisé détecté automatiquement."""
    conn.execute(
        "UPDATE franchisees SET validated = ? WHERE id = ?", (int(validated), franchisee_id)
    )


def reorder(conn: sqlite3.Connection, newsletter_id: int, ordered_ids: Sequence[int]) -> None:
    """Fixe l'ordre d'affichage des franchisés (ceux non cités suivent)."""
    _common.reorder(conn, "franchisees", _SCOPE, (newsletter_id,), ordered_ids)


def delete(conn: sqlite3.Connection, franchisee_id: int) -> None:
    """Supprime un franchisé."""
    conn.execute("DELETE FROM franchisees WHERE id = ?", (franchisee_id,))
