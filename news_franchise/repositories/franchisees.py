"""Dépôt des franchisés identifiés (rubrique 5)."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections.abc import Iterable, Sequence

from news_franchise.db.connection import transaction
from news_franchise.models import Franchisee
from news_franchise.repositories import _common

_COLUMNS = (
    "id, newsletter_id, name, brands, location, store_count, source_name, source_url,"
    " article_id, validated, position, confidence, evidence, trigger_terms, edited, dismissed"
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
        confidence=row["confidence"],
        evidence=row["evidence"],
        trigger_terms=json.loads(row["trigger_terms"]),
        edited=bool(row["edited"]),
        dismissed=bool(row["dismissed"]),
    )


def _values(item: Franchisee) -> tuple[object, ...]:
    """Valeurs des colonnes de fiche (hors id, position et indicateurs de protection)."""
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
        item.confidence,
        item.evidence,
        json.dumps(item.trigger_terms, ensure_ascii=False),
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
            " source_name, source_url, article_id, validated, confidence, evidence,"
            " trigger_terms, position, edited, dismissed)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (*_values(item), item.position, int(item.edited), int(item.dismissed)),
        )
        item.id = cursor.lastrowid
    return item


def list_for_newsletter(
    conn: sqlite3.Connection,
    newsletter_id: int,
    validated_only: bool = False,
    include_dismissed: bool = False,
) -> list[Franchisee]:
    """Franchisés d'une newsletter dans l'ordre d'affichage.

    validated_only : seulement ceux validés par l'utilisateur ; include_dismissed : inclure
    les suggestions écartées (exclues par défaut).
    """
    sql = f"SELECT {_COLUMNS} FROM franchisees WHERE {_SCOPE}"
    if validated_only:
        sql += " AND validated = 1"
    if not include_dismissed:
        sql += " AND dismissed = 0"
    rows = conn.execute(sql + " ORDER BY position, id", (newsletter_id,))
    return [_from_row(row) for row in rows]


def update(conn: sqlite3.Connection, franchisee: Franchisee) -> Franchisee:
    """Enregistre une modification faite par l'utilisateur (LookupError si absent).

    La fiche est marquée « edited » : la détection automatique n'y touchera plus.
    """
    franchisee_id = _common.require_id(franchisee.id, "Franchisé")
    item = dataclasses.replace(franchisee)
    cursor = conn.execute(
        "UPDATE franchisees SET newsletter_id = ?, name = ?, brands = ?, location = ?,"
        " store_count = ?, source_name = ?, source_url = ?, article_id = ?, validated = ?,"
        " confidence = ?, evidence = ?, trigger_terms = ?,"
        " position = COALESCE(?, position), edited = 1 WHERE id = ?",
        (*_values(item), item.position, franchisee_id),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"Franchisé introuvable (id {franchisee_id}).")
    updated = get(conn, franchisee_id)
    assert updated is not None
    return updated


def apply_auto_update(conn: sqlite3.Connection, franchisee: Franchisee) -> bool:
    """Met à jour une suggestion de la détection automatique.

    Ne fait rien si la fiche a été validée, modifiée, écartée par l'utilisateur ou saisie
    à la main ; renvoie True si la fiche a été mise à jour.
    """
    franchisee_id = _common.require_id(franchisee.id, "Franchisé")
    item = dataclasses.replace(franchisee)
    cursor = conn.execute(
        "UPDATE franchisees SET name = ?, brands = ?, location = ?, store_count = ?,"
        " source_name = ?, source_url = ?, article_id = ?, confidence = ?, evidence = ?,"
        " trigger_terms = ?"
        " WHERE id = ? AND validated = 0 AND edited = 0 AND dismissed = 0"
        " AND confidence IS NOT NULL",
        (
            item.name,
            item.brands,
            item.location,
            item.store_count,
            item.source_name,
            item.source_url,
            item.article_id,
            item.confidence,
            item.evidence,
            json.dumps(item.trigger_terms, ensure_ascii=False),
            franchisee_id,
        ),
    )
    return cursor.rowcount > 0


def delete_stale_suggestions(
    conn: sqlite3.Connection, newsletter_id: int, keep_ids: Iterable[int]
) -> int:
    """Supprime les suggestions automatiques que la détection ne trouve plus.

    Seules les fiches jamais touchées par l'utilisateur (non validées, non modifiées, non
    écartées, créées par la détection) sont concernées. Renvoie le nombre supprimé.
    """
    keep = set(keep_ids)
    removed = 0
    for row in conn.execute(
        "SELECT id FROM franchisees WHERE newsletter_id = ? AND validated = 0 AND edited = 0"
        " AND dismissed = 0 AND confidence IS NOT NULL",
        (newsletter_id,),
    ).fetchall():
        if row["id"] not in keep:
            conn.execute("DELETE FROM franchisees WHERE id = ?", (row["id"],))
            removed += 1
    return removed


def set_validated(conn: sqlite3.Connection, franchisee_id: int, validated: bool) -> None:
    """Valide (True) ou invalide (False) un franchisé détecté automatiquement."""
    conn.execute(
        "UPDATE franchisees SET validated = ? WHERE id = ?", (int(validated), franchisee_id)
    )


def set_dismissed(conn: sqlite3.Connection, franchisee_id: int, dismissed: bool) -> None:
    """Écarte (True) une suggestion : elle n'apparaît plus et n'est jamais recréée par
    la détection ; False la rétablit."""
    conn.execute(
        "UPDATE franchisees SET dismissed = ? WHERE id = ?", (int(dismissed), franchisee_id)
    )


def reorder(conn: sqlite3.Connection, newsletter_id: int, ordered_ids: Sequence[int]) -> None:
    """Fixe l'ordre d'affichage des franchisés (ceux non cités suivent)."""
    _common.reorder(conn, "franchisees", _SCOPE, (newsletter_id,), ordered_ids)


def delete(conn: sqlite3.Connection, franchisee_id: int) -> None:
    """Supprime un franchisé."""
    conn.execute("DELETE FROM franchisees WHERE id = ?", (franchisee_id,))
