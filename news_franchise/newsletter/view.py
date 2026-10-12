"""Données de la newsletter prêtes à afficher, communes à l'aperçu, à l'e-mail et à l'A4.

Tout est préparé ici (sélection, ordre, dates en français, libellés au singulier ou au
pluriel) : les gabarits ne font qu'afficher. Seuls les éléments retenus (articles) et
validés (franchisés) sont publiés, dans l'ordre choisi pendant la relecture.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, replace

from news_franchise.config import Settings
from news_franchise.content.service import plural
from news_franchise.models import DEFAULT_PLANS_LABEL, validate_month
from news_franchise.newsletter.dates import format_day, format_month
from news_franchise.newsletter.theme import Theme, load_theme
from news_franchise.repositories import (
    articles,
    brands,
    franchisees,
    meetings,
    newsletters,
    openings,
)

OPPORTUNITY_LABEL = "Opportunité emplacements"


class EmptyNewsletterError(ValueError):
    """La newsletter n'a encore aucun contenu publiable (message en français)."""


class NewsletterNotFoundError(LookupError):
    """Aucune newsletter pour ce mois."""


@dataclass(frozen=True)
class FrontFigure:
    """Chiffre de la Une : valeur, libellé accordé, ancre de la rubrique concernée (None si
    la rubrique est vide, donc absente de la newsletter)."""

    value: int
    label: str
    anchor: str | None


@dataclass(frozen=True)
class ArticleItem:
    """Fiche actualité (rubriques 1 et 2)."""

    title: str
    url: str
    source: str
    brand: str | None
    sector: str | None
    date_label: str | None
    excerpt: str | None
    opportunity: bool


@dataclass(frozen=True)
class PhotoItem:
    """Photo d'ouverture (nom relatif au dossier photos) et sa légende."""

    file_name: str
    caption: str | None


@dataclass(frozen=True)
class OpeningItem:
    """Ouverture (rubrique 3) ; main_photo = photo principale."""

    brand: str
    location: str
    date_label: str | None
    description: str | None
    main_photo: PhotoItem | None
    other_photos: tuple[PhotoItem, ...] = ()


@dataclass(frozen=True)
class MeetingItem:
    """Enseigne rencontrée (rubrique 4)."""

    brand: str
    date_label: str | None
    comment: str | None


@dataclass(frozen=True)
class FranchiseeItem:
    """Franchisé validé (rubrique 5) ; store_count_label est None si le nombre est inconnu."""

    name: str
    brands: str | None
    location: str | None
    store_count_label: str | None
    source_name: str
    source_url: str


@dataclass(frozen=True)
class PlansItem:
    """Lien vers les plans de développement (rubrique 6)."""

    url: str
    label: str


Item = ArticleItem | OpeningItem | MeetingItem | FranchiseeItem | PlansItem


@dataclass(frozen=True)
class Section:
    """Rubrique de la newsletter ; hidden = vide, à masquer dans les exports.

    number est le numéro fixe de la rubrique (1 à 6, comme dans la relecture) ;
    display_number est le numéro affiché au lecteur : les rubriques publiées sont
    renumérotées sans trou (1, 2, 3…) quand une rubrique vide est masquée. None si masquée.
    """

    key: str  # rubrique_1 … rubrique_6
    number: int
    title: str
    kind: str  # articles, openings, meetings, franchisees, plans
    items: tuple[Item, ...] = field(default_factory=tuple)
    display_number: int | None = None

    @property
    def anchor(self) -> str:
        """Ancre HTML de la rubrique (liens du sommaire)."""
        return f"rubrique-{self.number}"

    @property
    def count(self) -> int:
        """Nombre d'éléments publiés."""
        return len(self.items)

    @property
    def hidden(self) -> bool:
        """Vrai si la rubrique est vide (elle n'est alors pas publiée)."""
        return not self.items


@dataclass(frozen=True)
class TocEntry:
    """Ligne du sommaire (number = numéro affiché, sans trou)."""

    number: int
    title: str
    anchor: str
    count: int
    count_label: str


@dataclass(frozen=True)
class NewsletterView:
    """Newsletter d'un mois, prête à afficher."""

    month: str
    month_label: str  # « Octobre 2026 »
    front_title: str
    front: tuple[FrontFigure, ...]
    sections: tuple[Section, ...]
    toc: tuple[TocEntry, ...]

    @property
    def visible_sections(self) -> tuple[Section, ...]:
        """Rubriques non vides, dans l'ordre."""
        return tuple(s for s in self.sections if not s.hidden)

    @property
    def article_urls(self) -> tuple[str, ...]:
        """Liens des articles publiés (rubriques 1 et 2), pour préparer les QR codes."""
        return tuple(
            item.url for s in self.sections for item in s.items if isinstance(item, ArticleItem)
        )

    @property
    def photo_files(self) -> tuple[str, ...]:
        """Photos publiées (noms relatifs), photo principale d'abord pour chaque ouverture."""
        files: list[str] = []
        for section in self.sections:
            for item in section.items:
                if isinstance(item, OpeningItem):
                    photos = ((item.main_photo,) if item.main_photo else ()) + item.other_photos
                    files += [p.file_name for p in photos]
        return tuple(files)


def _store_count_label(count: int | None) -> str | None:
    """« 12 points de vente », « 1 point de vente » ; None si inconnu (ou 0)."""
    if not count:
        return None
    return f"{count} {plural(count, 'point de vente', 'points de vente')}"


def _items_label(count: int, kind: str) -> str:
    """Libellé du nombre d'éléments pour le sommaire."""
    words = {
        "articles": ("article", "articles"),
        "openings": ("ouverture", "ouvertures"),
        "meetings": ("enseigne", "enseignes"),
        "franchisees": ("franchisé", "franchisés"),
        "plans": ("lien", "liens"),
    }[kind]
    return f"{count} {plural(count, *words)}"


def build_newsletter_view(
    conn: sqlite3.Connection, month: str, settings: Settings, theme: Theme | None = None
) -> NewsletterView:
    """Prépare la newsletter du mois AAAA-MM pour l'aperçu et les exports.

    Ne garde que les articles retenus et les franchisés validés, dans l'ordre choisi ;
    marque les rubriques vides comme masquées ; calcule la Une (comme front_page_figures)
    et le sommaire. Lève NewsletterNotFoundError si le mois n'existe pas,
    EmptyNewsletterError si aucune rubrique n'a de contenu, ThemeError si le thème est
    invalide. settings est réservé aux exports (dossiers de données).
    """
    month = validate_month(month)
    theme = theme or load_theme()
    newsletter = newsletters.get(conn, month)
    if newsletter is None or newsletter.id is None:
        raise NewsletterNotFoundError(f"Aucune newsletter pour {format_month(month)}.")
    nid = newsletter.id
    brand_names = {b.id: b.name for b in brands.list_all(conn)}
    titles = theme.section_titles

    def article_items(rubric: int) -> tuple[ArticleItem, ...]:
        return tuple(
            ArticleItem(
                title=a.title,
                url=a.url,
                source=a.source_name,
                brand=brand_names.get(a.brand_id) or a.brand_label,
                sector=a.sector,
                date_label=format_day(a.published_at) if a.published_at else None,
                excerpt=a.excerpt,
                opportunity=a.is_opportunity,
            )
            for a in articles.list_for_rubric(conn, nid, rubric, selected_only=True)
        )

    opening_items = []
    for o in openings.list_for_newsletter(conn, nid):
        assert o.id is not None
        photos = tuple(PhotoItem(p.file_name, p.caption) for p in openings.list_photos(conn, o.id))
        opening_items.append(
            OpeningItem(
                brand=o.brand_name,
                location=o.location,
                date_label=format_day(o.opening_date) if o.opening_date else None,
                description=o.description,
                main_photo=photos[0] if photos else None,
                other_photos=photos[1:],
            )
        )
    meeting_items = tuple(
        MeetingItem(
            brand=m.brand_name,
            date_label=format_day(m.meeting_date) if m.meeting_date else None,
            comment=m.comment,
        )
        for m in meetings.list_for_newsletter(conn, nid)
    )
    franchisee_items = tuple(
        FranchiseeItem(
            name=f.name,
            brands=f.brands or None,
            location=f.location,
            store_count_label=_store_count_label(f.store_count),
            source_name=f.source_name,
            source_url=f.source_url,
        )
        for f in franchisees.list_for_newsletter(conn, nid, validated_only=True)
    )
    plans_items: tuple[PlansItem, ...] = ()
    if newsletter.development_plans_url:
        plans_items = (
            PlansItem(
                url=newsletter.development_plans_url,
                label=newsletter.development_plans_label or DEFAULT_PLANS_LABEL,
            ),
        )

    raw_sections = (
        Section("rubrique_1", 1, titles["rubrique_1"], "articles", article_items(1)),
        Section("rubrique_2", 2, titles["rubrique_2"], "articles", article_items(2)),
        Section("rubrique_3", 3, titles["rubrique_3"], "openings", tuple(opening_items)),
        Section("rubrique_4", 4, titles["rubrique_4"], "meetings", meeting_items),
        Section("rubrique_5", 5, titles["rubrique_5"], "franchisees", franchisee_items),
        Section("rubrique_6", 6, titles["rubrique_6"], "plans", plans_items),
    )
    sections: list[Section] = []
    shown = 0
    for section in raw_sections:
        if not section.hidden:
            shown += 1
            section = replace(section, display_number=shown)
        sections.append(section)
    if not shown:
        raise EmptyNewsletterError(
            f"La newsletter de {format_month(month)} est encore vide : retenez des articles, "
            "validez des franchisés ou saisissez le contenu interne avant de la publier."
        )

    def anchor(number: int) -> str | None:
        section = sections[number - 1]
        return None if section.hidden else section.anchor

    figures = newsletters.front_page_figures(conn, nid)
    front = (
        FrontFigure(
            figures.openings, plural(figures.openings, "ouverture", "ouvertures"), anchor(3)
        ),
        FrontFigure(
            figures.brands_met,
            plural(figures.brands_met, "enseigne rencontrée", "enseignes rencontrées"),
            anchor(4),
        ),
        FrontFigure(
            figures.franchisees,
            plural(figures.franchisees, "franchisé identifié", "franchisés identifiés"),
            anchor(5),
        ),
    )
    toc = tuple(
        TocEntry(s.display_number, s.title, s.anchor, s.count, _items_label(s.count, s.kind))
        for s in sections
        if s.display_number is not None
    )
    return NewsletterView(
        month=month,
        month_label=format_month(month),
        front_title=titles["une"],
        front=front,
        sections=tuple(sections),
        toc=toc,
    )
