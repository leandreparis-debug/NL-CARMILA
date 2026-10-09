"""Dépôt des enseignes et synchronisation avec config/enseignes.yaml."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from news_franchise.brand_catalog import BRANDS_FILE, load_brand_catalog, slugify
from news_franchise.db.connection import transaction
from news_franchise.models import Brand

_COLUMNS = "id, name, slug, sector, aliases, tracked, case_sensitive"


@dataclass(frozen=True)
class BrandSyncResult:
    """Bilan d'une synchronisation du référentiel (noms des enseignes concernées)."""

    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)


def _from_row(row: sqlite3.Row) -> Brand:
    """Ligne SQL → Brand."""
    return Brand(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        sector=row["sector"],
        aliases=json.loads(row["aliases"]),
        tracked=bool(row["tracked"]),
        case_sensitive=bool(row["case_sensitive"]),
    )


def list_all(conn: sqlite3.Connection, tracked_only: bool = False) -> list[Brand]:
    """Enseignes par ordre alphabétique ; tracked_only pour n'avoir que celles suivies."""
    sql = f"SELECT {_COLUMNS} FROM brands"
    if tracked_only:
        sql += " WHERE tracked = 1"
    return [_from_row(row) for row in conn.execute(sql + " ORDER BY name COLLATE NOCASE")]


def get(conn: sqlite3.Connection, brand_id: int) -> Brand | None:
    """Enseigne par identifiant, ou None."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM brands WHERE id = ?", (brand_id,)).fetchone()
    return _from_row(row) if row else None


def get_by_name(conn: sqlite3.Connection, name: str) -> Brand | None:
    """Enseigne par nom exact, ou None."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM brands WHERE name = ?", (name,)).fetchone()
    return _from_row(row) if row else None


def get_by_slug(conn: sqlite3.Connection, slug: str) -> Brand | None:
    """Enseigne par slug, ou None."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM brands WHERE slug = ?", (slug,)).fetchone()
    return _from_row(row) if row else None


def sync_from_yaml(conn: sqlite3.Connection, path: Path = BRANDS_FILE) -> BrandSyncResult:
    """Synchronise la table brands avec le fichier YAML, en une transaction.

    Ajoute les nouvelles enseignes, met à jour secteur, alias et case_sensitive des
    existantes (repérées par leur nom) et repasse tracked = 1 ; une enseigne retirée du
    YAML n'est jamais supprimée : elle passe tracked = 0. Lève BrandCatalogError si le
    fichier est invalide (la base n'est alors pas modifiée).
    """
    entries = load_brand_catalog(path)
    result = BrandSyncResult()
    with transaction(conn):
        existing = {brand.name: brand for brand in list_all(conn)}
        for entry in entries:
            aliases = list(entry.aliases)
            brand = existing.get(entry.name)
            if brand is None:
                conn.execute(
                    "INSERT INTO brands (name, slug, sector, aliases, tracked, case_sensitive)"
                    " VALUES (?, ?, ?, ?, 1, ?)",
                    (
                        entry.name,
                        slugify(entry.name),
                        entry.sector,
                        json.dumps(aliases, ensure_ascii=False),
                        int(entry.case_sensitive),
                    ),
                )
                result.added.append(entry.name)
            elif (brand.sector, brand.aliases, brand.tracked, brand.case_sensitive) != (
                entry.sector,
                aliases,
                True,
                entry.case_sensitive,
            ):
                conn.execute(
                    "UPDATE brands SET sector = ?, aliases = ?, tracked = 1, case_sensitive = ?"
                    " WHERE id = ?",
                    (
                        entry.sector,
                        json.dumps(aliases, ensure_ascii=False),
                        int(entry.case_sensitive),
                        brand.id,
                    ),
                )
                result.updated.append(entry.name)
        names = {entry.name for entry in entries}
        for name, brand in existing.items():
            if name not in names and brand.tracked:
                conn.execute("UPDATE brands SET tracked = 0 WHERE id = ?", (brand.id,))
                result.untracked.append(name)
    return result
