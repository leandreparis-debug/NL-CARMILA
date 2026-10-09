"""Sources de veille candidates et enseignes suivies (données uniquement)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CandidateSite:
    """Site d'actualité candidat, dont on cherche le flux RSS/Atom."""

    name: str
    site_url: str


CANDIDATE_SITES: tuple[CandidateSite, ...] = (
    CandidateSite("Toute la Franchise", "https://www.toute-la-franchise.com"),
    CandidateSite("Franchise Magazine", "https://www.franchise-magazine.com"),
    CandidateSite("Observatoire de la Franchise", "https://www.observatoiredelafranchise.fr"),
    CandidateSite("L'Officiel de la Franchise", "https://www.officieldelafranchise.fr"),
    CandidateSite("AC Franchise", "https://www.ac-franchise.com"),
)

GOOGLE_NEWS_NAME = "Google Actualités"
GOOGLE_NEWS_SEARCH_URL = "https://news.google.com/rss/search"
GOOGLE_NEWS_PARAMS = "hl=fr&gl=FR&ceid=FR:fr"
GOOGLE_NEWS_QUERY_TEMPLATE = '"{brand}" when:30d'

BRANDS: tuple[str, ...] = (
    "Adopt",
    "Comptoir de Mathilde",
    "Leonidas",
    "Mira Mira",
    "Dreams Donuts",
    "O'Tacos",
    "Jeff de Bruges",
    "Crêpe Touch",
    "Pokawa",
    "G La Dalle",
    "Easy Cash",
    "Yogurt Factory",
    "Wycon",
    "Dunkin' Donuts",
    "Chopstix",
)
