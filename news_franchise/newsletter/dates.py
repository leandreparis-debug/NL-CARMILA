"""Dates en français écrites par l'application (indépendantes de la langue de Windows).

Convention : le premier jour du mois s'écrit « 1er » (« 1er janvier 2026 »), comme le veut
l'usage typographique français ; les autres jours en chiffres (« 12 octobre 2026 »). Les
mois sont en minuscules dans une date, avec majuscule initiale dans un titre
(« Octobre 2026 »).
"""

from __future__ import annotations

from datetime import date, datetime

from news_franchise.collect.periods import PARIS
from news_franchise.dates import FRENCH_MONTHS


def day_label(day: int) -> str:
    """« 1er » pour le premier du mois, sinon le numéro du jour."""
    return "1er" if day == 1 else str(day)


def format_day(value: date | datetime) -> str:
    """« 12 octobre 2026 », « 1er février 2026 » (un datetime est lu à l'heure de Paris)."""
    if isinstance(value, datetime):
        value = value.astimezone(PARIS).date() if value.tzinfo else value.date()
    return f"{day_label(value.day)} {FRENCH_MONTHS[value.month - 1]} {value.year}"


def format_month(month: str) -> str:
    """Mois AAAA-MM en toutes lettres, avec majuscule initiale (« Octobre 2026 »)."""
    year, number = (int(part) for part in month.split("-"))
    return f"{FRENCH_MONTHS[number - 1].capitalize()} {year}"


def capitalize_first(text: str) -> str:
    """Majuscule sur la première lettre seulement (« 12 octobre » → inchangé ;
    « octobre 2026 » → « Octobre 2026 »)."""
    return text[:1].upper() + text[1:] if text else text
