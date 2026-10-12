"""Actions du contenu interne : ouvertures et photos, enseignes rencontrées, lien des plans.

Toutes les saisies sont validées ici ; les erreurs sont des FormError (message en français
rattaché au champ fautif), comme pour la relecture.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from news_franchise.collect.text import fold
from news_franchise.content.photos import PhotoError, SavedPhoto, process_photo
from news_franchise.models import Brand, Meeting, Newsletter, Opening, OpeningPhoto
from news_franchise.repositories import franchisees, meetings, newsletters, openings
from news_franchise.review.service import (
    OTHER_BRAND,
    FormError,
    date_field,
    text_field,
    url_field,
)

MAX_OPENING_BRAND = 100
MAX_LOCATION = 150
MAX_DESCRIPTION = 400
MAX_CAPTION = 200
MAX_MEETING_BRAND = 100
MAX_COMMENT = 200
MAX_PLANS_LABEL = 100
MAX_QUICK_LINES = 100


# --------------------------------------------------------------------------- Une


@dataclass(frozen=True)
class FrontPage:
    """Chiffres de la Une (calculés) et franchisés restant à valider."""

    openings: int
    brands_met: int
    franchisees: int
    franchisees_to_validate: int


def front_page(conn: sqlite3.Connection, newsletter_id: int) -> FrontPage:
    """Chiffres de la Une, toujours calculés (jamais saisis) : ouvertures, enseignes
    rencontrées, franchisés validés ; plus le nombre de suggestions encore à valider."""
    figures = newsletters.front_page_figures(conn, newsletter_id)
    pending = sum(
        1 for f in franchisees.list_for_newsletter(conn, newsletter_id) if not f.validated
    )
    return FrontPage(figures.openings, figures.brands_met, figures.franchisees, pending)


def plural(count: int, singular: str, plural_form: str) -> str:
    """Libellé au singulier pour 0 ou 1, au pluriel au-delà (« 1 ouverture », « 2 ouvertures »)."""
    return singular if count <= 1 else plural_form


# --------------------------------------------------------------------------- ouvertures


def _previous_month(month: str) -> str:
    """Mois précédent d'un mois AAAA-MM."""
    year, number = (int(part) for part in month.split("-"))
    return f"{year - 1}-12" if number == 1 else f"{year:04d}-{number - 1:02d}"


def opening_from_form(
    form: Mapping[str, str],
    newsletter: Newsletter,
    brand_list: Sequence[Brand],
    base: Opening | None = None,
) -> tuple[Opening, str | None]:
    """Ouverture d'après le formulaire (ajout ou modification) et avertissement éventuel.

    L'avertissement (non bloquant) signale une date d'ouverture hors du mois de la
    newsletter et du mois précédent. Lève FormError si une saisie est invalide.
    """
    choice = (form.get("enseigne") or "").strip()
    if choice == OTHER_BRAND:
        brand_name = text_field(
            form, "enseigne_autre", "Autre enseigne", MAX_OPENING_BRAND, required=True
        )
    elif not choice:
        raise FormError("Choisissez l'enseigne qui a ouvert.", "enseigne")
    else:
        brand = next((b for b in brand_list if b.name == choice), None)
        if brand is None:
            raise FormError("Enseigne inconnue.", "enseigne")
        brand_name = brand.name
    location = text_field(
        form, "lieu", "Lieu (centre commercial et ville)", MAX_LOCATION, required=True
    )
    opening_date = date_field(form, "date", "Date d'ouverture")
    description = text_field(form, "description", "Description", MAX_DESCRIPTION)
    assert newsletter.id is not None
    values = {
        "brand_name": brand_name or "",
        "location": location or "",
        "opening_date": opening_date,
        "description": description,
    }
    opening = replace(base, **values) if base else Opening(newsletter_id=newsletter.id, **values)
    warning = None
    if opening_date is not None:
        allowed = {newsletter.month, _previous_month(newsletter.month)}
        if opening_date.strftime("%Y-%m") not in allowed:
            warning = (
                f"La date d'ouverture ({opening_date:%d/%m/%Y}) ne tombe ni dans le mois de la "
                "newsletter ni dans le mois précédent : vérifiez-la."
            )
    return opening, warning


@dataclass
class UploadResult:
    """Bilan d'un envoi de photos."""

    saved: list[SavedPhoto] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def add_photos(
    conn: sqlite3.Connection,
    opening: Opening,
    files: Sequence[tuple[str, bytes]],
    photos_dir: Path,
    month: str,
    max_photos: int,
) -> UploadResult:
    """Traite et enregistre les photos envoyées (nom d'origine, contenu), dans la limite
    de max_photos par ouverture. Chaque fichier refusé donne un message ; les autres sont
    enregistrés."""
    assert opening.id is not None
    result = UploadResult()
    existing = len(openings.list_photos(conn, opening.id))
    for name, data in files:
        if not name and not data:
            continue  # champ fichier laissé vide
        if existing + len(result.saved) >= max_photos:
            result.errors.append(
                f"« {name} » n'a pas été ajoutée : {max_photos} photos au maximum par ouverture."
            )
            continue
        try:
            saved = process_photo(data, photos_dir, month, name)
        except PhotoError as exc:
            result.errors.append(str(exc))
            continue
        openings.add_photo(conn, OpeningPhoto(opening_id=opening.id, file_name=saved.file_name))
        result.saved.append(saved)
    if not result.saved and not result.errors:
        result.errors.append("Aucune photo choisie.")
    return result


def set_main_photo(conn: sqlite3.Connection, opening_id: int, photo_id: int) -> None:
    """Fait d'une photo la photo principale (première, utilisée en priorité dans les exports)."""
    openings.reorder_photos(conn, opening_id, [photo_id])


def update_caption(conn: sqlite3.Connection, photo: OpeningPhoto, form: Mapping[str, str]) -> None:
    """Enregistre la légende d'une photo (vide autorisé)."""
    assert photo.id is not None
    caption = text_field(form, "legende", "Légende", MAX_CAPTION)
    conn.execute("UPDATE opening_photos SET caption = ? WHERE id = ?", (caption, photo.id))


# --------------------------------------------------------------------------- enseignes rencontrées


def meeting_from_form(
    form: Mapping[str, str], newsletter_id: int, base: Meeting | None = None
) -> Meeting:
    """Enseigne rencontrée d'après le formulaire (ajout ou modification)."""
    values = {
        "brand_name": text_field(form, "enseigne", "Enseigne", MAX_MEETING_BRAND, required=True)
        or "",
        "meeting_date": date_field(form, "date", "Date"),
        "comment": text_field(form, "commentaire", "Commentaire", MAX_COMMENT),
    }
    return replace(base, **values) if base else Meeting(newsletter_id=newsletter_id, **values)


def _meeting_key(name: str) -> str:
    """Forme de comparaison d'un nom d'enseigne (casse, accents, apostrophes, espaces)."""
    return fold(name)


def is_duplicate_meeting(
    conn: sqlite3.Connection, newsletter_id: int, name: str, exclude_id: int | None = None
) -> bool:
    """Vrai si une enseigne de même nom (sans tenir compte de la casse ni des accents) est
    déjà dans les rencontres du mois."""
    key = _meeting_key(name)
    return any(
        _meeting_key(m.brand_name) == key and m.id != exclude_id
        for m in meetings.list_for_newsletter(conn, newsletter_id)
    )


@dataclass
class QuickAddResult:
    """Bilan d'un ajout rapide : enseignes ajoutées et doublons ignorés."""

    added: list[str] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)


def quick_add_meetings(conn: sqlite3.Connection, newsletter_id: int, text: str) -> QuickAddResult:
    """Ajout rapide : une enseigne par ligne ; lignes vides ignorées ; doublons du mois (casse
    et accents non pris en compte), y compris dans la liste elle-même, ignorés et signalés.

    Lève FormError si une ligne est trop longue ou s'il y a trop de lignes.
    """
    lines = [" ".join(line.split()) for line in (text or "").splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise FormError("Saisissez au moins une enseigne (une par ligne).", "liste")
    if len(lines) > MAX_QUICK_LINES:
        raise FormError(f"{MAX_QUICK_LINES} lignes au maximum à la fois.", "liste")
    too_long = [line for line in lines if len(line) > MAX_MEETING_BRAND]
    if too_long:
        raise FormError(
            f"Ligne trop longue ({MAX_MEETING_BRAND} caractères au plus) : "
            f"« {too_long[0][:40]}… ».",
            "liste",
        )
    seen = {_meeting_key(m.brand_name) for m in meetings.list_for_newsletter(conn, newsletter_id)}
    result = QuickAddResult()
    for name in lines:
        key = _meeting_key(name)
        if key in seen:
            result.ignored.append(name)
            continue
        seen.add(key)
        meetings.add(conn, Meeting(newsletter_id=newsletter_id, brand_name=name))
        result.added.append(name)
    return result


# --------------------------------------------------------------------------- plans


def save_plans_link(
    conn: sqlite3.Connection, newsletter: Newsletter, form: Mapping[str, str]
) -> None:
    """Enregistre le lien des plans de développement (format http/https vérifié, le lien
    n'est jamais appelé : il est souvent interne et demande une connexion)."""
    assert newsletter.id is not None
    url = url_field(form, "lien", "Lien vers les plans de développement")
    label = text_field(form, "libelle", "Libellé du lien", MAX_PLANS_LABEL)
    newsletters.set_development_plans(conn, newsletter.id, url, label)


def clear_plans_link(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    """Retire le lien des plans de développement (et son libellé)."""
    assert newsletter.id is not None
    newsletters.set_development_plans(conn, newsletter.id, None, None)


def last_draft(conn: sqlite3.Connection) -> Newsletter | None:
    """Newsletter en cours de préparation : la plus récente au statut Brouillon."""
    return next((n for n in newsletters.list_all(conn) if n.status == "draft"), None)


def count_openings(conn: sqlite3.Connection, newsletter_id: int) -> int:
    """Nombre d'ouvertures du mois."""
    return len(openings.list_for_newsletter(conn, newsletter_id))


def opening_date_value(value: date | None) -> str:
    """Valeur du champ date (AAAA-MM-JJ) ou chaîne vide."""
    return value.isoformat() if value else ""
