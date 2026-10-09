"""Dépôt des ouvertures Carmila Franchise (rubrique 3) et de leurs photos."""

from __future__ import annotations

import dataclasses
import logging
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from news_franchise.db.connection import transaction
from news_franchise.models import Opening, OpeningPhoto
from news_franchise.repositories import _common
from news_franchise.repositories._common import from_iso_date, to_iso_date

logger = logging.getLogger(__name__)

_COLUMNS = "id, newsletter_id, brand_name, location, opening_date, description, position"
_PHOTO_COLUMNS = "id, opening_id, file_name, caption, position"
_SCOPE = "newsletter_id = ?"
_PHOTO_SCOPE = "opening_id = ?"


def _from_row(row: sqlite3.Row) -> Opening:
    """Ligne SQL → Opening."""
    return Opening(
        id=row["id"],
        newsletter_id=row["newsletter_id"],
        brand_name=row["brand_name"],
        location=row["location"],
        opening_date=from_iso_date(row["opening_date"]),
        description=row["description"],
        position=row["position"],
    )


def _photo_from_row(row: sqlite3.Row) -> OpeningPhoto:
    """Ligne SQL → OpeningPhoto."""
    return OpeningPhoto(
        id=row["id"],
        opening_id=row["opening_id"],
        file_name=row["file_name"],
        caption=row["caption"],
        position=row["position"],
    )


def get(conn: sqlite3.Connection, opening_id: int) -> Opening | None:
    """Ouverture par identifiant, ou None."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM openings WHERE id = ?", (opening_id,)).fetchone()
    return _from_row(row) if row else None


def add(conn: sqlite3.Connection, opening: Opening) -> Opening:
    """Ajoute une ouverture (en fin de liste si position est None) et la renvoie avec son id."""
    item = dataclasses.replace(opening)
    with transaction(conn):
        if item.position is None:
            item.position = _common.next_position(conn, "openings", _SCOPE, (item.newsletter_id,))
        cursor = conn.execute(
            "INSERT INTO openings (newsletter_id, brand_name, location, opening_date,"
            " description, position) VALUES (?, ?, ?, ?, ?, ?)",
            (
                item.newsletter_id,
                item.brand_name,
                item.location,
                to_iso_date(item.opening_date),
                item.description,
                item.position,
            ),
        )
        item.id = cursor.lastrowid
    return item


def list_for_newsletter(conn: sqlite3.Connection, newsletter_id: int) -> list[Opening]:
    """Ouvertures d'une newsletter, dans l'ordre d'affichage."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM openings WHERE {_SCOPE} ORDER BY position, id", (newsletter_id,)
    )
    return [_from_row(row) for row in rows]


def update(conn: sqlite3.Connection, opening: Opening) -> Opening:
    """Enregistre les modifications d'une ouverture (LookupError si elle n'existe pas)."""
    opening_id = _common.require_id(opening.id, "Ouverture")
    item = dataclasses.replace(opening)
    cursor = conn.execute(
        "UPDATE openings SET newsletter_id = ?, brand_name = ?, location = ?, opening_date = ?,"
        " description = ?, position = COALESCE(?, position) WHERE id = ?",
        (
            item.newsletter_id,
            item.brand_name,
            item.location,
            to_iso_date(item.opening_date),
            item.description,
            item.position,
            opening_id,
        ),
    )
    if cursor.rowcount == 0:
        raise LookupError(f"Ouverture introuvable (id {opening_id}).")
    updated = get(conn, opening_id)
    assert updated is not None
    return updated


def reorder(conn: sqlite3.Connection, newsletter_id: int, ordered_ids: Sequence[int]) -> None:
    """Fixe l'ordre d'affichage des ouvertures (celles non citées suivent)."""
    _common.reorder(conn, "openings", _SCOPE, (newsletter_id,), ordered_ids)


def delete(conn: sqlite3.Connection, opening_id: int, photos_dir: Path | None = None) -> None:
    """Supprime une ouverture et ses photos (lignes en cascade ; fichiers aussi si
    photos_dir est donné)."""
    photos = list_photos(conn, opening_id)
    conn.execute("DELETE FROM openings WHERE id = ?", (opening_id,))
    if photos_dir is not None:
        for photo in photos:
            remove_photo_file(photos_dir, photo.file_name)


# --------------------------------------------------------------------------- photos


def add_photo(conn: sqlite3.Connection, photo: OpeningPhoto) -> OpeningPhoto:
    """Enregistre une photo d'ouverture (fichier déjà copié dans le dossier photos).

    file_name est relatif au dossier photos ; ValueError si c'est un chemin absolu.
    """
    item = dataclasses.replace(photo)
    with transaction(conn):
        if item.position is None:
            item.position = _common.next_position(
                conn, "opening_photos", _PHOTO_SCOPE, (item.opening_id,)
            )
        cursor = conn.execute(
            "INSERT INTO opening_photos (opening_id, file_name, caption, position)"
            " VALUES (?, ?, ?, ?)",
            (item.opening_id, item.file_name, item.caption, item.position),
        )
        item.id = cursor.lastrowid
    return item


def get_photo(conn: sqlite3.Connection, photo_id: int) -> OpeningPhoto | None:
    """Photo par identifiant, ou None."""
    row = conn.execute(
        f"SELECT {_PHOTO_COLUMNS} FROM opening_photos WHERE id = ?", (photo_id,)
    ).fetchone()
    return _photo_from_row(row) if row else None


def list_photos(conn: sqlite3.Connection, opening_id: int) -> list[OpeningPhoto]:
    """Photos d'une ouverture, dans l'ordre d'affichage."""
    rows = conn.execute(
        f"SELECT {_PHOTO_COLUMNS} FROM opening_photos WHERE {_PHOTO_SCOPE} ORDER BY position, id",
        (opening_id,),
    )
    return [_photo_from_row(row) for row in rows]


def reorder_photos(conn: sqlite3.Connection, opening_id: int, ordered_ids: Sequence[int]) -> None:
    """Fixe l'ordre des photos d'une ouverture (celles non citées suivent)."""
    _common.reorder(conn, "opening_photos", _PHOTO_SCOPE, (opening_id,), ordered_ids)


def delete_photo(conn: sqlite3.Connection, photo_id: int, photos_dir: Path) -> None:
    """Supprime une photo : la ligne en base et le fichier dans photos_dir.

    Aucune erreur si le fichier a déjà disparu.
    """
    photo = get_photo(conn, photo_id)
    if photo is None:
        return
    conn.execute("DELETE FROM opening_photos WHERE id = ?", (photo_id,))
    remove_photo_file(photos_dir, photo.file_name)


def remove_photo_file(photos_dir: Path, file_name: str) -> None:
    """Supprime un fichier photo s'il existe, sans jamais sortir du dossier photos."""
    root = photos_dir.resolve()
    path = (root / file_name).resolve()
    if not path.is_relative_to(root) or path == root:
        logger.warning("Suppression refusée hors du dossier photos : %s", file_name)
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Impossible de supprimer la photo %s", path, exc_info=True)
