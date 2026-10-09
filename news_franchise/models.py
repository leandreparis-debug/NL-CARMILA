"""Modèles de données de la newsletter (dataclasses validées à la construction).

Règle du projet : aucun lien inventé. Toute URL stockée commence par http:// ou https://
(contrôle ici en Python, et contrainte CHECK en SQL).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

NEWSLETTER_STATUSES = ("draft", "reviewed", "exported")
RUBRIC_NEW_FRANCHISES = 1
RUBRIC_BRAND_NEWS = 2
ARTICLE_RUBRICS = (RUBRIC_NEW_FRANCHISES, RUBRIC_BRAND_NEWS)
RUN_STATUSES = ("running", "success", "partial", "failed")
RUN_FINAL_STATUSES = ("success", "partial", "failed")
BODY_TEXT_MAX_LENGTH = 20_000


# --------------------------------------------------------------------------- validation


def validate_month(month: str) -> str:
    """Vérifie un mois de newsletter au format AAAA-MM et le renvoie.

    Lève ValueError (message en français) si le format ou le mois est invalide.
    """
    if not isinstance(month, str) or not MONTH_PATTERN.match(month.strip()):
        raise ValueError(
            f"Mois de newsletter invalide : {month!r}. Format attendu : AAAA-MM (ex. 2026-10)."
        )
    return month.strip()


def validate_url(url: str | None, field_name: str = "url") -> str:
    """Vérifie qu'une URL est absolue et commence par http:// ou https://, et la renvoie.

    Lève ValueError si l'URL est vide ou d'un autre type (aucun lien inventé ni relatif).
    """
    value = url.strip() if isinstance(url, str) else ""
    parts = urlsplit(value)
    if not value or parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(
            f"Lien invalide ({field_name}) : {url!r}. "
            "Le lien doit être une adresse réelle commençant par http:// ou https://."
        )
    return value


def validate_photo_file_name(file_name: str) -> str:
    """Vérifie qu'un nom de photo est relatif au dossier photos (jamais un chemin absolu).

    Les sous-dossiers sont acceptés avec « / » (ex. « 2026-10/ouverture.jpg »).
    """
    value = (file_name or "").strip()
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or ".." in value
        or value.endswith("/")
    ):
        raise ValueError(
            f"Nom de photo invalide : {file_name!r}. Attendu : un nom relatif au dossier "
            "photos (ex. « ouverture-lyon.jpg »), sans chemin absolu ni « .. »."
        )
    return value


def _require_text(value: str, label: str) -> str:
    """Vérifie qu'un texte obligatoire n'est pas vide et le renvoie nettoyé."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Le champ « {label} » est obligatoire.")
    return value.strip()


def _check_position(position: int | None) -> None:
    """Vérifie qu'une position d'affichage est un entier positif ou nul (ou None)."""
    if position is not None and (not isinstance(position, int) or position < 0):
        raise ValueError(f"Position invalide : {position!r} (entier positif attendu).")


# --------------------------------------------------------------------------- modèles


@dataclass
class Newsletter:
    """Newsletter d'un mois donné (AAAA-MM). La Une n'est jamais stockée : voir
    FrontPageFigures."""

    month: str
    status: str = "draft"
    development_plans_url: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide le mois, le statut et le lien des plans de développement."""
        self.month = validate_month(self.month)
        if self.status not in NEWSLETTER_STATUSES:
            raise ValueError(
                f"Statut de newsletter invalide : {self.status!r} "
                f"(attendu : {', '.join(NEWSLETTER_STATUSES)})."
            )
        if self.development_plans_url is not None:
            self.development_plans_url = validate_url(
                self.development_plans_url, "development_plans_url"
            )


@dataclass
class Brand:
    """Enseigne du référentiel (config/enseignes.yaml). tracked=False si retirée du YAML."""

    name: str
    slug: str
    sector: str = ""
    aliases: list[str] = field(default_factory=list)
    tracked: bool = True
    case_sensitive: bool = False  # True : majuscule initiale exigée lors de la détection
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide le nom et le slug."""
        self.name = _require_text(self.name, "nom de l'enseigne")
        self.slug = _require_text(self.slug, "slug de l'enseigne")


@dataclass
class Article:
    """Actualité de veille (rubrique 1 : nouvelles franchises ; rubrique 2 : enseignes).

    url est l'adresse réelle de l'article d'origine (obligatoire). position=None à l'ajout
    signifie « à la fin de la rubrique ».
    """

    newsletter_id: int
    rubric: int
    title: str
    source_name: str
    url: str
    brand_id: int | None = None
    sector: str | None = None
    published_at: datetime | None = None
    excerpt: str | None = None
    is_opportunity: bool = False
    selected: bool = True
    position: int | None = None
    collected_at: datetime | None = None
    body_text: str | None = None  # texte brut de l'article, jamais affiché tel quel
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide la rubrique, le titre, la source, l'URL et la position ; tronque body_text."""
        if self.body_text is not None:
            self.body_text = self.body_text[:BODY_TEXT_MAX_LENGTH]
        if self.rubric not in ARTICLE_RUBRICS:
            raise ValueError(f"Rubrique d'article invalide : {self.rubric!r} (1 ou 2).")
        self.title = _require_text(self.title, "titre")
        self.source_name = _require_text(self.source_name, "source")
        self.url = validate_url(self.url)
        _check_position(self.position)


@dataclass
class Franchisee:
    """Franchisé identifié (rubrique 5), toujours rattaché à l'article qui le mentionne.

    store_count est souvent inconnu (None). validated passe à True après relecture.
    """

    newsletter_id: int
    name: str
    source_name: str
    source_url: str
    brands: str = ""
    location: str | None = None
    store_count: int | None = None
    article_id: int | None = None
    validated: bool = False
    position: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide le nom, la source, l'URL de la source et le nombre de points de vente."""
        self.name = _require_text(self.name, "nom du franchisé")
        self.source_name = _require_text(self.source_name, "source")
        self.source_url = validate_url(self.source_url, "source_url")
        if self.store_count is not None and (
            not isinstance(self.store_count, int) or self.store_count < 0
        ):
            raise ValueError(
                f"Nombre de points de vente invalide : {self.store_count!r} "
                "(entier positif ou vide)."
            )
        _check_position(self.position)


@dataclass
class Opening:
    """Ouverture Carmila Franchise du mois (rubrique 3, saisie interne)."""

    newsletter_id: int
    brand_name: str
    location: str
    opening_date: date | None = None
    description: str | None = None
    position: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide l'enseigne et le lieu."""
        self.brand_name = _require_text(self.brand_name, "enseigne")
        self.location = _require_text(self.location, "lieu")
        _check_position(self.position)


@dataclass
class OpeningPhoto:
    """Photo d'une ouverture. file_name est relatif à <données>/photos."""

    opening_id: int
    file_name: str
    caption: str | None = None
    position: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide le nom de fichier (relatif) et la position."""
        self.file_name = validate_photo_file_name(self.file_name)
        _check_position(self.position)


@dataclass
class Meeting:
    """Enseigne rencontrée ce mois-ci (rubrique 4, saisie interne)."""

    newsletter_id: int
    brand_name: str
    meeting_date: date | None = None
    comment: str | None = None
    position: int | None = None
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide l'enseigne et la position."""
        self.brand_name = _require_text(self.brand_name, "enseigne")
        _check_position(self.position)


@dataclass
class CollectionRun:
    """Exécution de la collecte de veille pour une newsletter."""

    newsletter_id: int
    started_at: datetime
    status: str = "running"
    finished_at: datetime | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    id: int | None = None

    def __post_init__(self) -> None:
        """Valide le statut."""
        if self.status not in RUN_STATUSES:
            raise ValueError(
                f"Statut de collecte invalide : {self.status!r} "
                f"(attendu : {', '.join(RUN_STATUSES)})."
            )


@dataclass(frozen=True)
class FrontPageFigures:
    """Chiffres de la Une, calculés à la volée (jamais stockés)."""

    openings: int = 0
    brands_met: int = 0
    franchisees: int = 0
