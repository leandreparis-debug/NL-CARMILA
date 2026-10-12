"""Actions de relecture : validation des saisies, ordre, ajout manuel, statut.

Règles : l'URL d'un article collecté n'est jamais modifiable (elle n'est pas lue dans les
formulaires) ; un lien ajouté à la main doit répondre (2xx après redirections) avant
d'être enregistré ; aucune donnée venant d'un site n'est réécrite.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from news_franchise.collect.excerpt import choose_excerpt, extract_page
from news_franchise.collect.periods import PARIS
from news_franchise.collect.text import html_to_text
from news_franchise.collect.urls import clean_url, url_key
from news_franchise.http_client import Fetcher
from news_franchise.models import Article, Brand, Franchisee, validate_url
from news_franchise.repositories import articles, franchisees, newsletters
from news_franchise.repositories._common import utcnow
from news_franchise.review.limits import Limits

STATUS_LABELS = {"draft": "Brouillon", "reviewed": "Relue", "exported": "Exportée"}
RUBRIC_TITLES = {1: "Rubrique 1 — Marché de la franchise", 2: "Rubrique 2 — Nos enseignes"}

MAX_TITLE = 300
MAX_EXCERPT = 1000
MAX_SOURCE = 120
MAX_SECTOR = 80
MAX_BRAND_LABEL = 100
MAX_NAME = 150
MAX_BRANDS = 200
MAX_LOCATION = 120
MAX_URL = 2000
MAX_STORE_COUNT = 100_000
OTHER_BRAND = "autre"


class FormError(ValueError):
    """Saisie refusée ; le message (en français) est affiché à côté du champ fautif."""

    def __init__(self, message: str, field: str | None = None) -> None:
        """field : nom du champ de formulaire concerné (None si aucun en particulier)."""
        super().__init__(message)
        self.field = field


class LinkError(FormError):
    """Lien ajouté à la main qui ne peut pas être vérifié."""


class LinkRefused(LinkError):
    """Le site répond mais refuse la lecture automatique (403, protection anti-robot).

    L'utilisateur peut alors confirmer lui-même que le lien affiche bien l'article.
    """

    def __init__(self, message: str, field: str | None, final_url: str) -> None:
        """final_url : adresse atteinte (après redirections éventuelles)."""
        super().__init__(message, field)
        self.final_url = final_url


# Réponses d'un site qui existe mais bloque les robots (lecture automatique refusée).
REFUSED_STATUSES = frozenset({401, 403, 406, 429, 503})


# --------------------------------------------------------------------------- vue d'ensemble


@dataclass(frozen=True)
class Counts:
    """Éléments retenus d'une newsletter."""

    selected_1: int = 0
    selected_2: int = 0
    validated: int = 0

    @property
    def total(self) -> int:
        """Total des éléments retenus (articles des rubriques 1 et 2, franchisés validés)."""
        return self.selected_1 + self.selected_2 + self.validated

    def for_rubric(self, rubric: int) -> int:
        """Articles retenus de la rubrique 1 ou 2."""
        return self.selected_1 if rubric == 1 else self.selected_2


@dataclass(frozen=True)
class NewsletterSummary:
    """Ligne de la liste des newsletters."""

    month: str
    status: str
    counts: Counts

    @property
    def status_label(self) -> str:
        """Statut en français."""
        return STATUS_LABELS.get(self.status, self.status)


def count_selected(conn: sqlite3.Connection, newsletter_id: int) -> Counts:
    """Articles retenus par rubrique et franchisés validés (non écartés)."""
    row = conn.execute(
        "SELECT"
        " (SELECT COUNT(*) FROM articles WHERE newsletter_id = :id AND rubric = 1"
        "  AND selected = 1) AS s1,"
        " (SELECT COUNT(*) FROM articles WHERE newsletter_id = :id AND rubric = 2"
        "  AND selected = 1) AS s2,"
        " (SELECT COUNT(*) FROM franchisees WHERE newsletter_id = :id AND validated = 1"
        "  AND dismissed = 0) AS v",
        {"id": newsletter_id},
    ).fetchone()
    return Counts(selected_1=row["s1"], selected_2=row["s2"], validated=row["v"])


def list_newsletters(conn: sqlite3.Connection) -> list[NewsletterSummary]:
    """Newsletters de la plus récente à la plus ancienne, avec leurs éléments retenus."""
    return [
        NewsletterSummary(n.month, n.status, count_selected(conn, n.id))  # type: ignore[arg-type]
        for n in newsletters.list_all(conn)
    ]


def review_warnings(conn: sqlite3.Connection, newsletter_id: int, limits: Limits) -> list[str]:
    """Avertissements (non bloquants) avant de marquer la newsletter comme relue."""
    counts = count_selected(conn, newsletter_id)
    warnings = []
    for rubric in (1, 2):
        if counts.for_rubric(rubric) > limits.for_rubric(rubric):
            warnings.append(
                f"{RUBRIC_TITLES[rubric]} : {counts.for_rubric(rubric)} articles retenus pour "
                f"une limite de {limits.for_rubric(rubric)}."
            )
    if counts.validated > limits.franchises:
        warnings.append(
            f"Franchisés identifiés : {counts.validated} validés pour une limite de "
            f"{limits.franchises}."
        )
    if counts.validated == 0:
        warnings.append("Aucun franchisé n'est validé : la rubrique 5 sera vide.")
    opening_count = conn.execute(
        "SELECT COUNT(*) FROM openings WHERE newsletter_id = ?", (newsletter_id,)
    ).fetchone()[0]
    if opening_count == 0:
        warnings.append("Aucune ouverture saisie : la rubrique 3 sera vide.")
    elif opening_count > limits.ouvertures:
        warnings.append(
            f"Ouvertures : {opening_count} saisies pour une limite de {limits.ouvertures}."
        )
    meeting_count = conn.execute(
        "SELECT COUNT(*) FROM meetings WHERE newsletter_id = ?", (newsletter_id,)
    ).fetchone()[0]
    if meeting_count == 0:
        warnings.append("Aucune enseigne rencontrée saisie : la rubrique 4 sera vide.")
    newsletter = newsletters.get_by_id(conn, newsletter_id)
    if newsletter is not None and not newsletter.development_plans_url:
        warnings.append("Pas de lien vers les plans de développement : la rubrique 6 sera vide.")
    if warnings:
        warnings.append(f"Rappel : la version imprimée doit tenir en {limits.pages_max} pages A4.")
    return warnings


# --------------------------------------------------------------------------- saisies


def text_field(
    form: Mapping[str, str], name: str, label: str, max_length: int, *, required: bool = False
) -> str | None:
    """Texte saisi, nettoyé ; None si vide. FormError si obligatoire et vide, ou trop long."""
    value = " ".join((form.get(name) or "").split())
    if not value:
        if required:
            raise FormError(f"Le champ « {label} » est obligatoire.", name)
        return None
    if len(value) > max_length:
        raise FormError(
            f"Le champ « {label} » est trop long ({len(value)} caractères, {max_length} au plus).",
            name,
        )
    return value


def date_field(form: Mapping[str, str], name: str, label: str) -> date | None:
    """Date AAAA-MM-JJ (champ date du navigateur) ; None si vide."""
    raw = (form.get(name) or "").strip()
    if not raw:
        return None
    try:
        value = date.fromisoformat(raw)
    except ValueError:
        raise FormError(
            f"Le champ « {label} » n'est pas une date valide (JJ/MM/AAAA).", name
        ) from None
    if not 1990 <= value.year <= 2100:
        raise FormError(f"Le champ « {label} » contient une année improbable ({value.year}).", name)
    return value


def store_count_field(form: Mapping[str, str], name: str) -> int | None:
    """Nombre de points de vente : vide autorisé, sinon entier ≥ 0."""
    raw = (form.get(name) or "").strip().replace(" ", "")
    if not raw:
        return None
    if not raw.isdigit() or int(raw) > MAX_STORE_COUNT:
        raise FormError(
            "Le nombre de points de vente doit être un nombre entier positif (ou rester vide).",
            name,
        )
    return int(raw)


def url_field(form: Mapping[str, str], name: str, label: str) -> str:
    """Lien http(s) obligatoire."""
    raw = (form.get(name) or "").strip()
    if not raw:
        raise FormError(f"Le champ « {label} » est obligatoire.", name)
    if len(raw) > MAX_URL:
        raise FormError(f"Le champ « {label} » est trop long.", name)
    try:
        return validate_url(raw, label)
    except ValueError:
        raise FormError(
            f"Le champ « {label} » doit être une adresse commençant par http:// ou https://.",
            name,
        ) from None


def _published_at(current: datetime | None, chosen: date | None) -> datetime | None:
    """Date de publication : l'heure d'origine est gardée si le jour ne change pas ;
    sinon midi, heure de Paris."""
    if chosen is None:
        return None
    if current is not None and current.astimezone(PARIS).date() == chosen:
        return current
    return datetime.combine(chosen, time(12, 0), tzinfo=PARIS).astimezone(UTC)


def _brand_choice(
    form: Mapping[str, str], brands: Sequence[Brand]
) -> tuple[Brand | None, str | None]:
    """Enseigne choisie : (enseigne suivie, None), (None, texte « Autre ») ou (None, None)."""
    choice = (form.get("enseigne") or "").strip()
    if not choice:
        return None, None
    if choice == OTHER_BRAND:
        label = text_field(form, "enseigne_autre", "Autre enseigne", MAX_BRAND_LABEL)
        if label is None:
            raise FormError(
                "Indiquez le nom de l'enseigne dans le champ « Autre enseigne ».", "enseigne_autre"
            )
        return None, label
    brand = next((b for b in brands if str(b.id) == choice), None)
    if brand is None:
        raise FormError("Enseigne inconnue.", "enseigne")
    return brand, None


def apply_article_form(
    article: Article, form: Mapping[str, str], brands: Sequence[Brand]
) -> Article:
    """Article modifié d'après le formulaire de sa carte.

    L'URL n'est jamais lue dans le formulaire : un champ « url » ajouté à la requête est
    ignoré. « Retenir » ne se règle pas ici (bouton rapide dédié). Lève FormError si une
    saisie est invalide.
    """
    brand, brand_label = _brand_choice(form, brands)
    sector = text_field(form, "secteur", "Secteur", MAX_SECTOR)
    if sector is None and brand is not None:
        sector = brand.sector or None
    return replace(
        article,
        is_opportunity="opportunite" in form,
        brand_id=brand.id if brand else None,
        brand_label=brand_label,
        sector=sector,
        title=text_field(form, "titre", "Titre", MAX_TITLE, required=True),
        published_at=_published_at(article.published_at, date_field(form, "date", "Date")),
        source_name=text_field(form, "source", "Source", MAX_SOURCE, required=True),
        excerpt=text_field(form, "extrait", "Premières lignes", MAX_EXCERPT),
        url=article.url,
    )


def apply_franchisee_form(fiche: Franchisee, form: Mapping[str, str]) -> Franchisee:
    """Franchisé modifié d'après le formulaire de sa carte.

    La source n'est pas modifiable ; « Valider » se règle avec le bouton rapide dédié.
    """
    return replace(
        fiche,
        name=text_field(form, "nom", "Nom", MAX_NAME, required=True),
        brands=text_field(form, "enseignes", "Enseigne(s)", MAX_BRANDS) or "",
        location=text_field(form, "lieu", "Ville ou région", MAX_LOCATION),
        store_count=store_count_field(form, "nombre"),
        source_url=fiche.source_url,
        source_name=fiche.source_name,
    )


# --------------------------------------------------------------------------- ordre


def parse_rank(raw: str | None, count: int) -> int:
    """Rang saisi (1 = en tête), borné entre 1 et count ; renvoie l'index (0 = en tête).

    Lève FormError si la saisie n'est pas un nombre entier.
    """
    value = (raw or "").strip()
    if not value.lstrip("-").isdigit():
        raise FormError("Le rang doit être un numéro (1 = en tête de liste).", "rang")
    return min(max(int(value), 1), max(count, 1)) - 1


def _target_index(ids: list[int], item_id: int, action: str, rank: str | None) -> int:
    """Nouvel index d'un élément selon l'action : haut, bas, tete, fin ou rang."""
    index = ids.index(item_id)
    if action == "haut":
        return max(index - 1, 0)
    if action == "bas":
        return min(index + 1, len(ids) - 1)
    if action == "tete":
        return 0
    if action == "fin":
        return len(ids) - 1
    if action == "rang":
        return parse_rank(rank, len(ids))
    raise FormError("Déplacement inconnu.")


def moved_order(ids: list[int], item_id: int, action: str, rank: str | None) -> list[int] | None:
    """Ordre après déplacement ; None si l'élément ne bouge pas."""
    target = _target_index(ids, item_id, action, rank)
    if target == ids.index(item_id):
        return None
    ids.remove(item_id)
    ids.insert(target, item_id)
    return ids


def move_article(
    conn: sqlite3.Connection, article: Article, action: str, rank: str | None = None
) -> bool:
    """Déplace un article dans sa rubrique : « haut », « bas », « tete », « fin » ou
    « rang » (rank = numéro saisi, borné). Renvoie False s'il ne bouge pas."""
    ids = [a.id for a in articles.list_for_rubric(conn, article.newsletter_id, article.rubric)]
    order = moved_order(ids, article.id, action, rank)  # type: ignore[arg-type]
    if order is None:
        return False
    articles.reorder(conn, article.newsletter_id, article.rubric, order)  # type: ignore[arg-type]
    return True


def move_franchisee(
    conn: sqlite3.Connection, fiche: Franchisee, action: str, rank: str | None = None
) -> bool:
    """Déplace un franchisé dans la liste (mêmes actions que move_article)."""
    ids = [f.id for f in franchisees.list_for_newsletter(conn, fiche.newsletter_id)]
    order = moved_order(ids, fiche.id, action, rank)  # type: ignore[arg-type]
    if order is None:
        return False
    franchisees.reorder(conn, fiche.newsletter_id, order)  # type: ignore[arg-type]
    return True


def change_rubric(
    conn: sqlite3.Connection,
    article: Article,
    target: str | None,
    form: Mapping[str, str],
    brands: Sequence[Brand],
) -> Article:
    """Déplace un article vers l'autre rubrique (en fin de liste).

    Vers la rubrique 2 (« Nos enseignes »), l'enseigne est obligatoire : une des enseignes
    suivies, ou « Autre » avec son nom. Vers la rubrique 1, l'article est conservé tel
    quel, avec son enseigne éventuelle. Lève FormError sinon.
    """
    if target not in ("1", "2") or int(target) == article.rubric:
        raise FormError("Rubrique de destination invalide.")
    assert article.id is not None
    if target == "1":
        return articles.move_to_rubric(
            conn, article.id, 1, article.brand_id, article.brand_label, article.sector
        )
    brand, label = _brand_choice(form, brands)
    if brand is None and label is None:
        raise FormError(
            "Choisissez l'enseigne de l'article pour le déplacer vers la rubrique 2.", "enseigne"
        )
    sector = brand.sector if brand and brand.sector else article.sector
    return articles.move_to_rubric(conn, article.id, 2, brand.id if brand else None, label, sector)


def keep_first(conn: sqlite3.Connection, newsletter_id: int, rubric: int, n: int) -> int:
    """Retient les n premiers articles de la rubrique (dans l'ordre affiché) et ne retient
    plus les suivants. Renvoie le nombre d'articles retenus."""
    rubric_articles = articles.list_for_rubric(conn, newsletter_id, rubric)
    for index, article in enumerate(rubric_articles):
        articles.set_selected(conn, article.id, index < n)  # type: ignore[arg-type]
    return min(n, len(rubric_articles))


def remove_franchisee(conn: sqlite3.Connection, fiche: Franchisee) -> None:
    """Retire un franchisé : une suggestion de la détection est écartée (elle ne
    reviendra pas à la prochaine détection) ; une fiche saisie à la main est supprimée."""
    assert fiche.id is not None
    if fiche.confidence is not None:
        franchisees.set_dismissed(conn, fiche.id, True)
    else:
        franchisees.delete(conn, fiche.id)


# --------------------------------------------------------------------------- ajout manuel


@dataclass(frozen=True)
class PagePreview:
    """Informations lues sur la page d'un lien ajouté à la main (pour pré-remplir)."""

    url: str  # adresse finale, après redirections
    title: str
    excerpt: str
    body_text: str
    source_name: str
    published: date | None


def _meta(soup: BeautifulSoup, *names: str) -> str:
    """Contenu de la première balise meta (property ou name) trouvée."""
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if isinstance(tag, Tag) and tag.get("content"):
            return html_to_text(str(tag.get("content")))
    return ""


def _published(soup: BeautifulSoup) -> date | None:
    """Date de publication annoncée par la page (article:published_time), si lisible."""
    raw = _meta(soup, "article:published_time", "datePublished", "date")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date() if raw else None
    except ValueError:
        return None


def preview_link(fetcher: Fetcher, url: str) -> PagePreview:
    """Vérifie qu'un lien répond (2xx après redirections) et lit titre et premières lignes.

    Le lien est demandé par l'utilisateur : robots.txt ne bloque pas cette vérification
    (une seule page lue, comme le ferait son navigateur). Lève LinkRefused si le site
    répond mais refuse la lecture automatique (403…), LinkError si le lien est invalide
    ou ne répond pas.
    """
    try:
        url = url_field({"lien": url}, "lien", "Lien")
    except FormError as exc:
        raise LinkError(str(exc), "lien") from None
    result = fetcher.fetch(url, check_robots=False)
    if result.status_code in REFUSED_STATUSES:
        raise LinkRefused(
            f"Le site refuse la lecture automatique de cette page ({result.error}) : "
            "l'application ne peut pas vérifier le lien elle-même.",
            "lien",
            result.final_url or url,
        )
    if not result.ok:
        raise LinkError(f"Le lien ne répond pas correctement : {result.error}", "lien")
    final_url = clean_url(validate_url(result.final_url or url))
    soup = BeautifulSoup(result.text or "", "html.parser")
    title = _meta(soup, "og:title", "twitter:title")
    if not title and isinstance(soup.find("h1"), Tag):
        title = html_to_text(soup.find("h1").get_text(" "))  # type: ignore[union-attr]
    if not title and soup.title is not None:
        title = html_to_text(soup.title.get_text(" "))
    page = extract_page(result.text or "")
    host = (urlsplit(final_url).hostname or "").removeprefix("www.")
    return PagePreview(
        url=final_url,
        title=title[:MAX_TITLE],
        excerpt=choose_excerpt(page, ""),
        body_text=page.body_text,
        source_name=(_meta(soup, "og:site_name") or host)[:MAX_SOURCE],
        published=_published(soup),
    )


def find_duplicate(conn: sqlite3.Connection, newsletter_id: int, url: str) -> Article | None:
    """Article du mois ayant déjà ce lien (après normalisation), ou None."""
    key = url_key(url)
    return next(
        (a for a in articles.list_for_newsletter(conn, newsletter_id) if url_key(a.url) == key),
        None,
    )


def add_manual_article(
    conn: sqlite3.Connection,
    newsletter_id: int,
    preview: PagePreview | None,
    form: Mapping[str, str],
    brands: Sequence[Brand],
    *,
    refused_url: str | None = None,
) -> Article:
    """Enregistre un article ajouté à la main (retenu, en fin de rubrique).

    preview : page lue et vérifiée par l'application. Si le site a refusé la lecture
    automatique (preview None, refused_url = adresse atteinte), l'utilisateur doit avoir
    coché « J'ai ouvert ce lien… » (champ « confirme ») : l'article est alors marqué
    « lien vérifié par l'utilisateur ». Lève FormError si une saisie est invalide, si la
    confirmation manque ou si l'article est déjà dans la newsletter.
    """
    rubric = 2 if form.get("rubrique") == "2" else 1
    if preview is None:
        if refused_url is None:
            raise FormError("Lien non vérifié.", "lien")
        if "confirme" not in form:
            raise FormError(
                "Cochez la case de confirmation : le site refuse la lecture automatique, "
                "l'application ne peut donc pas vérifier ce lien elle-même.",
                "confirme",
            )
        url = clean_url(validate_url(refused_url))
    else:
        url = preview.url
    if find_duplicate(conn, newsletter_id, url) is not None:
        raise FormError("Cet article est déjà dans la newsletter de ce mois.", "lien")
    draft = Article(
        newsletter_id=newsletter_id,
        rubric=rubric,
        title=(preview.title if preview else "") or "-",
        source_name=(preview.source_name if preview else "") or "-",
        url=url,
        body_text=(preview.body_text or None) if preview else None,
        collected_at=utcnow(),
        selected=True,
        link_verified_by_user=preview is None,
    )
    article = apply_article_form(draft, form, brands)
    added = articles.add(conn, article)
    if added is None:
        raise FormError("Cet article est déjà dans la newsletter de ce mois.", "lien")
    return added


def restore_franchisee(conn: sqlite3.Connection, fiche: Franchisee) -> None:
    """Restaure une suggestion écartée : elle redevient une suggestion non validée."""
    assert fiche.id is not None
    franchisees.set_dismissed(conn, fiche.id, False)
    franchisees.set_validated(conn, fiche.id, False)


def add_manual_franchisee(
    conn: sqlite3.Connection, newsletter_id: int, form: Mapping[str, str], fetcher: Fetcher
) -> Franchisee:
    """Enregistre un franchisé saisi à la main ; son lien source est obligatoire et vérifié."""
    name = text_field(form, "nom", "Nom", MAX_NAME, required=True)
    brands = text_field(form, "enseignes", "Enseigne(s)", MAX_BRANDS) or ""
    location = text_field(form, "lieu", "Ville ou région", MAX_LOCATION)
    count = store_count_field(form, "nombre")
    source_name = text_field(form, "source", "Source", MAX_SOURCE)
    try:
        preview = preview_link(fetcher, form.get("lien_source") or "")
    except LinkError as exc:
        raise LinkError(str(exc), "lien_source") from None
    return franchisees.add(
        conn,
        Franchisee(
            newsletter_id=newsletter_id,
            name=name or "",
            brands=brands,
            location=location,
            store_count=count,
            source_name=source_name or preview.source_name,
            source_url=preview.url,
            validated="valider" in form,
            edited=True,
        ),
    )
