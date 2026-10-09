"""Dépôt des articles de veille (rubriques 1 et 2)."""

from __future__ import annotations

import dataclasses
import json
import sqlite3
from collections.abc import Sequence

from news_franchise.db.connection import transaction
from news_franchise.models import ARTICLE_RUBRICS, Article, clip_evidence
from news_franchise.repositories import _common
from news_franchise.repositories._common import (
    from_iso_datetime,
    to_iso_datetime,
    utcnow,
)

_COLUMNS = (
    "id, newsletter_id, rubric, brand_id, sector, title, published_at, source_name, url,"
    " excerpt, is_opportunity, selected, position, collected_at, body_text,"
    " opportunity_source, opportunity_evidence, opportunity_terms"
)
_SCOPE = "newsletter_id = ? AND rubric = ?"


def _from_row(row: sqlite3.Row) -> Article:
    """Ligne SQL → Article."""
    return Article(
        id=row["id"],
        newsletter_id=row["newsletter_id"],
        rubric=row["rubric"],
        brand_id=row["brand_id"],
        sector=row["sector"],
        title=row["title"],
        published_at=from_iso_datetime(row["published_at"]),
        source_name=row["source_name"],
        url=row["url"],
        excerpt=row["excerpt"],
        is_opportunity=bool(row["is_opportunity"]),
        selected=bool(row["selected"]),
        position=row["position"],
        collected_at=from_iso_datetime(row["collected_at"]),
        body_text=row["body_text"],
        opportunity_source=row["opportunity_source"],
        opportunity_evidence=row["opportunity_evidence"],
        opportunity_terms=json.loads(row["opportunity_terms"]),
    )


def _check_rubric(rubric: int) -> None:
    """Vérifie le numéro de rubrique."""
    if rubric not in ARTICLE_RUBRICS:
        raise ValueError(f"Rubrique d'article invalide : {rubric!r} (1 ou 2).")


def get(conn: sqlite3.Connection, article_id: int) -> Article | None:
    """Article par identifiant, ou None."""
    row = conn.execute(f"SELECT {_COLUMNS} FROM articles WHERE id = ?", (article_id,)).fetchone()
    return _from_row(row) if row else None


def add(conn: sqlite3.Connection, article: Article) -> Article | None:
    """Ajoute un article et le renvoie avec son identifiant.

    Renvoie None, sans erreur, si la même URL existe déjà pour cette newsletter
    (dédoublonnage). Si article.position est None, l'article est placé en fin de rubrique ;
    si collected_at est None, il prend la date courante. ValueError si l'URL n'est pas
    http(s) (contrôle fait à la construction de l'Article).
    """
    article = dataclasses.replace(
        article
    )  # revalide (URL, rubrique...) et évite les effets de bord
    with transaction(conn):
        if article.position is None:
            article.position = _common.next_position(
                conn, "articles", _SCOPE, (article.newsletter_id, article.rubric)
            )
        if article.collected_at is None:
            article.collected_at = utcnow()
        cursor = conn.execute(
            "INSERT INTO articles (newsletter_id, rubric, brand_id, sector, title, published_at,"
            " source_name, url, excerpt, is_opportunity, selected, position, collected_at,"
            " body_text)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (newsletter_id, url) DO NOTHING",
            (
                article.newsletter_id,
                article.rubric,
                article.brand_id,
                article.sector,
                article.title,
                to_iso_datetime(article.published_at),
                article.source_name,
                article.url,
                article.excerpt,
                int(article.is_opportunity),
                int(article.selected),
                article.position,
                to_iso_datetime(article.collected_at),
                article.body_text,
            ),
        )
        if cursor.rowcount == 0:
            return None
        article.id = cursor.lastrowid
    return article


def list_for_rubric(
    conn: sqlite3.Connection, newsletter_id: int, rubric: int, selected_only: bool = False
) -> list[Article]:
    """Articles d'une rubrique dans l'ordre d'affichage (position) ; selected_only pour
    n'avoir que les articles retenus."""
    _check_rubric(rubric)
    sql = f"SELECT {_COLUMNS} FROM articles WHERE {_SCOPE}"
    if selected_only:
        sql += " AND selected = 1"
    rows = conn.execute(sql + " ORDER BY position, id", (newsletter_id, rubric))
    return [_from_row(row) for row in rows]


def update(conn: sqlite3.Connection, article: Article) -> Article:
    """Enregistre les modifications d'un article existant (modification par l'utilisateur).

    Si le repère « opportunité » change, il passe en origine « manual » : la détection
    automatique n'y touchera plus. La preuve de détection n'est pas modifiée.

    ValueError si l'URL est déjà utilisée par un autre article du même mois ;
    LookupError si l'article n'existe pas.
    """
    article_id = _common.require_id(article.id, "Article")
    article = dataclasses.replace(article)
    try:
        cursor = conn.execute(
            "UPDATE articles SET newsletter_id = ?, rubric = ?, brand_id = ?, sector = ?,"
            " title = ?, published_at = ?, source_name = ?, url = ?, excerpt = ?,"
            " opportunity_source = CASE WHEN is_opportunity <> ? THEN 'manual'"
            " ELSE opportunity_source END,"
            " is_opportunity = ?, selected = ?, position = COALESCE(?, position),"
            " body_text = ? WHERE id = ?",
            (
                article.newsletter_id,
                article.rubric,
                article.brand_id,
                article.sector,
                article.title,
                to_iso_datetime(article.published_at),
                article.source_name,
                article.url,
                article.excerpt,
                int(article.is_opportunity),
                int(article.is_opportunity),
                int(article.selected),
                article.position,
                article.body_text,
                article_id,
            ),
        )
    except sqlite3.IntegrityError as exc:
        if "UNIQUE" in str(exc):
            raise ValueError("Un autre article de ce mois a déjà ce lien.") from exc
        raise
    if cursor.rowcount == 0:
        raise LookupError(f"Article introuvable (id {article_id}).")
    updated = get(conn, article_id)
    assert updated is not None
    return updated


def set_opportunity(conn: sqlite3.Connection, article_id: int, is_opportunity: bool) -> None:
    """Pose ou retire le repère « opportunité » à la main (origine « manual » : la détection
    automatique ne modifiera plus cet article)."""
    conn.execute(
        "UPDATE articles SET is_opportunity = ?, opportunity_source = 'manual' WHERE id = ?",
        (int(is_opportunity), article_id),
    )


def apply_auto_opportunity(
    conn: sqlite3.Connection,
    article_id: int,
    is_opportunity: bool,
    evidence: str | None,
    terms: Sequence[str],
) -> bool:
    """Enregistre le résultat de la détection automatique (origine « auto »).

    Ne fait rien si le repère a été modifié à la main ; renvoie True si l'article a été
    mis à jour.
    """
    cursor = conn.execute(
        "UPDATE articles SET is_opportunity = ?, opportunity_source = 'auto',"
        " opportunity_evidence = ?, opportunity_terms = ?"
        " WHERE id = ? AND COALESCE(opportunity_source, '') <> 'manual'",
        (
            int(is_opportunity),
            clip_evidence(evidence) if is_opportunity else None,
            json.dumps(list(terms) if is_opportunity else [], ensure_ascii=False),
            article_id,
        ),
    )
    return cursor.rowcount > 0


def list_for_newsletter(conn: sqlite3.Connection, newsletter_id: int) -> list[Article]:
    """Tous les articles d'une newsletter (rubrique 1 puis 2, dans l'ordre d'affichage)."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM articles WHERE newsletter_id = ? ORDER BY rubric, position, id",
        (newsletter_id,),
    )
    return [_from_row(row) for row in rows]


def set_selected(conn: sqlite3.Connection, article_id: int, selected: bool) -> None:
    """Retient (True) ou écarte (False) un article de la newsletter."""
    conn.execute("UPDATE articles SET selected = ? WHERE id = ?", (int(selected), article_id))


def reorder(
    conn: sqlite3.Connection, newsletter_id: int, rubric: int, ordered_ids: Sequence[int]
) -> None:
    """Fixe l'ordre d'affichage d'une rubrique (les articles non cités suivent)."""
    _check_rubric(rubric)
    _common.reorder(conn, "articles", _SCOPE, (newsletter_id, rubric), ordered_ids)


def delete(conn: sqlite3.Connection, article_id: int) -> None:
    """Supprime un article (les franchisés liés gardent leur source, article_id devient NULL)."""
    conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
