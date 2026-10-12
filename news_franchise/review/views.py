"""Pages de relecture : liste des newsletters, relecture d'un mois, ajouts manuels.

Toute action qui modifie passe par POST puis redirection (PRG), avec un message de
confirmation ou d'erreur. Les formulaires sont protégés par jeton CSRF.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask.typing import ResponseReturnValue

from news_franchise.collect.periods import PARIS, previous_month
from news_franchise.collect.views import app_now, month_label
from news_franchise.db.connection import get_db
from news_franchise.http_client import Fetcher
from news_franchise.models import Article, Franchisee, Newsletter, validate_month
from news_franchise.repositories import articles, brands, franchisees, newsletters
from news_franchise.review import service
from news_franchise.review.limits import LIMITS_FILE, Limits, load_limits
from news_franchise.review.service import FormError, LinkError

bp = Blueprint("review", __name__, url_prefix="/newsletters")

TABS = {"rubrique-1": 1, "rubrique-2": 2, "franchises": 5}
ARTICLE_FILTERS = {
    "tous": "Tout",
    "retenus": "Retenus",
    "non-retenus": "Non retenus",
    "opportunites": "Opportunités",
}
FRANCHISEE_FILTERS = {"tous": "Tout", "valides": "Validés", "a-valider": "À valider"}


# --------------------------------------------------------------------------- outils


def _limits() -> Limits:
    """Limites relues à chaque affichage ; un fichier invalide est signalé une fois par page."""
    limits, error = load_limits(current_app.config.get("NF_LIMITS_FILE", LIMITS_FILE))
    if error:
        flash(error, "warning")
    return limits


def _newsletter(month: str) -> Newsletter:
    """Newsletter du mois ; 404 si le mois est invalide ou n'existe pas."""
    try:
        month = validate_month(month)
    except ValueError:
        abort(404)
    newsletter = newsletters.get(get_db(), month)
    if newsletter is None or newsletter.id is None:
        abort(404)
    return newsletter


def _article(newsletter: Newsletter, article_id: int) -> Article:
    """Article de cette newsletter ; 404 sinon."""
    article = articles.get(get_db(), article_id)
    if article is None or article.newsletter_id != newsletter.id:
        abort(404)
    return article


def _franchisee(newsletter: Newsletter, franchisee_id: int) -> Franchisee:
    """Franchisé (non écarté) de cette newsletter ; 404 sinon."""
    fiche = franchisees.get(get_db(), franchisee_id)
    if fiche is None or fiche.newsletter_id != newsletter.id or fiche.dismissed:
        abort(404)
    return fiche


def _tab_of(article: Article) -> str:
    """Onglet d'un article."""
    return f"rubrique-{article.rubric}"


def _back(month: str, tab: str, anchor: str = "") -> ResponseReturnValue:
    """Redirection vers l'onglet (en gardant le filtre choisi) et l'élément concerné."""
    filters = FRANCHISEE_FILTERS if tab == "franchises" else ARTICLE_FILTERS
    chosen = request.form.get("filtre", "tous")
    query = {"filtre": chosen} if chosen in filters and chosen != "tous" else {}
    target = url_for("review.month", month=month, tab=tab, **query)
    return redirect(target + (f"#{anchor}" if anchor else ""))


def _fetcher() -> Fetcher:
    """Récupérateur HTTP (injectable dans les tests via NF_FETCHER_FACTORY)."""
    return current_app.config.get("NF_FETCHER_FACTORY", Fetcher)()


def _brand_list() -> list[Any]:
    """Enseignes suivies, pour la liste déroulante."""
    return brands.list_all(get_db(), tracked_only=True)


def _date_value(article: Article) -> str:
    """Valeur du champ date (AAAA-MM-JJ, jour de Paris)."""
    return article.published_at.astimezone(PARIS).date().isoformat() if article.published_at else ""


def _filter_articles(items: list[Article], chosen: str) -> list[Article]:
    """Articles selon le filtre choisi."""
    if chosen == "retenus":
        return [a for a in items if a.selected]
    if chosen == "non-retenus":
        return [a for a in items if not a.selected]
    if chosen == "opportunites":
        return [a for a in items if a.is_opportunity]
    return items


def _filter_franchisees(items: list[Franchisee], chosen: str) -> list[Franchisee]:
    """Franchisés selon le filtre choisi."""
    if chosen == "valides":
        return [f for f in items if f.validated]
    if chosen == "a-valider":
        return [f for f in items if not f.validated]
    return items


# --------------------------------------------------------------------------- liste


@bp.get("/")
def index() -> ResponseReturnValue:
    """Liste des newsletters (de la plus récente à la plus ancienne)."""
    return render_template(
        "review/list.html",
        summaries=service.list_newsletters(get_db()),
        default_month=previous_month(app_now()),
        month_label=month_label,
    )


@bp.post("/")
def open_month() -> ResponseReturnValue:
    """Crée (si besoin) puis ouvre la newsletter du mois choisi."""
    try:
        month = validate_month((request.form.get("mois") or "").strip())
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("review.index"))
    existed = newsletters.get(get_db(), month) is not None
    newsletters.get_or_create(get_db(), month)
    if not existed:
        flash(f"Newsletter de {month_label(month)} créée.", "success")
    return redirect(url_for("review.month", month=month, tab="rubrique-1"))


# --------------------------------------------------------------------------- relecture


@bp.get("/<month>/")
def month_home(month: str) -> ResponseReturnValue:
    """Ouvre le premier onglet."""
    return redirect(url_for("review.month", month=month, tab="rubrique-1"))


@bp.get("/<month>/<tab>")
def month(month: str, tab: str) -> ResponseReturnValue:
    """Page de relecture d'un mois : onglet rubrique 1, rubrique 2 ou franchisés."""
    if tab not in TABS:
        abort(404)
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    conn = get_db()
    limits = _limits()
    counts = service.count_selected(conn, newsletter.id)
    context: dict[str, Any] = {
        "newsletter": newsletter,
        "month_label": month_label(newsletter.month),
        "status_label": service.STATUS_LABELS.get(newsletter.status, newsletter.status),
        "tab": tab,
        "tabs": [
            (
                "rubrique-1",
                "Rubrique 1 — Marché de la franchise",
                counts.selected_1,
                limits.rubrique_1,
            ),
            ("rubrique-2", "Rubrique 2 — Nos enseignes", counts.selected_2, limits.rubrique_2),
            (
                "franchises",
                "Rubrique 5 — Franchisés identifiés",
                counts.validated,
                limits.franchises,
            ),
        ],
        "limits": limits,
    }
    if tab == "franchises":
        chosen = request.args.get("filtre", "tous")
        chosen = chosen if chosen in FRANCHISEE_FILTERS else "tous"
        items = franchisees.list_for_newsletter(conn, newsletter.id)
        context.update(
            filters=FRANCHISEE_FILTERS,
            filtre=chosen,
            items=_filter_franchisees(items, chosen),
            total=len(items),
            count=counts.validated,
            limit=limits.franchises,
            positions={f.id: i for i, f in enumerate(items)},
        )
        return render_template("review/franchisees.html", **context)

    rubric = TABS[tab]
    chosen = request.args.get("filtre", "tous")
    chosen = chosen if chosen in ARTICLE_FILTERS else "tous"
    items = articles.list_for_rubric(conn, newsletter.id, rubric)
    context.update(
        rubric=rubric,
        filters=ARTICLE_FILTERS,
        filtre=chosen,
        items=_filter_articles(items, chosen),
        total=len(items),
        count=counts.for_rubric(rubric),
        limit=limits.for_rubric(rubric),
        positions={a.id: i for i, a in enumerate(items)},
        brand_list=_brand_list(),
        date_value=_date_value,
        other_brand=service.OTHER_BRAND,
    )
    return render_template("review/articles.html", **context)


@bp.post("/<month>/statut")
def set_status(month: str) -> ResponseReturnValue:
    """Marque la newsletter comme relue (avec avertissements) ou la repasse en brouillon."""
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    tab = request.form.get("onglet", "rubrique-1")
    tab = tab if tab in TABS else "rubrique-1"
    if request.form.get("statut") == "relue":
        for warning in service.review_warnings(get_db(), newsletter.id, _limits()):
            flash(warning, "warning")
        newsletters.set_status(get_db(), newsletter.id, "reviewed")
        flash(f"Newsletter de {month_label(month)} marquée comme relue.", "success")
    elif request.form.get("statut") == "brouillon":
        newsletters.set_status(get_db(), newsletter.id, "draft")
        flash(f"Newsletter de {month_label(month)} repassée en brouillon.", "success")
    else:
        flash("Action inconnue.", "error")
    return redirect(url_for("review.month", month=month, tab=tab))


# --------------------------------------------------------------------------- articles


@bp.post("/<month>/articles/<int:article_id>")
def save_article(month: str, article_id: int) -> ResponseReturnValue:
    """Enregistre la carte d'un article (le lien n'est jamais modifié)."""
    newsletter = _newsletter(month)
    article = _article(newsletter, article_id)
    try:
        updated = service.apply_article_form(article, request.form, _brand_list())
        articles.update(get_db(), updated)
    except FormError as exc:
        flash(f"Article non enregistré : {exc}", "error")
    else:
        flash("Article enregistré.", "success")
    return _back(month, _tab_of(article), f"article-{article_id}")


@bp.post("/<month>/articles/<int:article_id>/retenir")
def toggle_article(month: str, article_id: int) -> ResponseReturnValue:
    """Retient ou ne retient plus un article (bouton rapide)."""
    newsletter = _newsletter(month)
    article = _article(newsletter, article_id)
    keep = request.form.get("valeur") == "1"
    articles.set_selected(get_db(), article_id, keep)
    flash("Article retenu." if keep else "Article retiré de la newsletter.", "success")
    return _back(month, _tab_of(article), f"article-{article_id}")


@bp.post("/<month>/articles/<int:article_id>/deplacer")
def move_article(month: str, article_id: int) -> ResponseReturnValue:
    """Monte ou descend un article dans sa rubrique."""
    newsletter = _newsletter(month)
    article = _article(newsletter, article_id)
    if not service.move_article(get_db(), article, request.form.get("sens", "")):
        flash("L'article est déjà en tête ou en fin de liste.", "warning")
    return _back(month, _tab_of(article), f"article-{article_id}")


@bp.route("/<month>/articles/<int:article_id>/supprimer", methods=["GET", "POST"])
def delete_article(month: str, article_id: int) -> ResponseReturnValue:
    """Confirmation (GET) puis suppression (POST) d'un article."""
    newsletter = _newsletter(month)
    article = _article(newsletter, article_id)
    if request.method == "GET":
        return render_template(
            "review/confirm_delete.html",
            month=month,
            what="cet article",
            label=article.title,
            action=url_for("review.delete_article", month=month, article_id=article_id),
            cancel=url_for("review.month", month=month, tab=_tab_of(article))
            + f"#article-{article_id}",
            note="L'article sera retiré de la base. Une prochaine collecte pourrait le "
            "retrouver ; pour l'écarter simplement, décochez plutôt « Retenir ».",
        )
    articles.delete(get_db(), article_id)
    flash(f"Article supprimé : « {article.title} ».", "success")
    return _back(month, _tab_of(article))


@bp.post("/<month>/<tab>/garder-premiers")
def keep_first(month: str, tab: str) -> ResponseReturnValue:
    """Ne retient que les N premiers articles de la rubrique (N = limite)."""
    if tab not in ("rubrique-1", "rubrique-2"):
        abort(404)
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    limit = _limits().for_rubric(TABS[tab])
    kept = service.keep_first(get_db(), newsletter.id, TABS[tab], limit)
    flash(f"Seuls les {kept} premiers articles sont retenus.", "success")
    return _back(month, tab)


# --------------------------------------------------------------------------- ajout d'article


def _add_article_page(
    newsletter: Newsletter,
    *,
    step: int,
    form: Mapping[str, str],
    preview: service.PagePreview | None = None,
    error: str | None = None,
    status: int = 200,
) -> ResponseReturnValue:
    """Formulaire d'ajout d'un article (étape 1 : lien ; étape 2 : compléter)."""
    return (
        render_template(
            "review/add_article.html",
            newsletter=newsletter,
            month_label=month_label(newsletter.month),
            step=step,
            form=form,
            preview=preview,
            error=error,
            brand_list=_brand_list(),
            other_brand=service.OTHER_BRAND,
        ),
        status,
    )


@bp.get("/<month>/ajouter-article")
def add_article(month: str) -> ResponseReturnValue:
    """Étape 1 : saisie du lien de l'article."""
    newsletter = _newsletter(month)
    rubric = "2" if request.args.get("rubrique") == "2" else "1"
    return _add_article_page(newsletter, step=1, form={"rubrique": rubric})


@bp.post("/<month>/ajouter-article/verifier")
def check_article(month: str) -> ResponseReturnValue:
    """Étape 2 : vérifie le lien (il doit répondre) et pré-remplit le formulaire.

    Rien n'est enregistré à cette étape.
    """
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    form = dict(request.form)
    try:
        with _fetcher() as fetcher:
            preview = service.preview_link(fetcher, form.get("lien", ""))
    except LinkError as exc:
        return _add_article_page(newsletter, step=1, form=form, error=str(exc), status=400)
    duplicate = service.find_duplicate(get_db(), newsletter.id, preview.url)
    if duplicate is not None:
        return _add_article_page(
            newsletter,
            step=1,
            form=form,
            error=f"Cet article est déjà dans la newsletter : « {duplicate.title} ».",
            status=400,
        )
    prefill = {
        "rubrique": form.get("rubrique", "1"),
        "titre": preview.title,
        "source": preview.source_name,
        "extrait": preview.excerpt,
        "date": preview.published.isoformat() if preview.published else "",
        "lien": preview.url,
    }
    return _add_article_page(newsletter, step=2, form=prefill, preview=preview)


@bp.post("/<month>/ajouter-article/enregistrer")
def save_new_article(month: str) -> ResponseReturnValue:
    """Enregistre l'article ajouté à la main ; le lien est revérifié à ce moment-là."""
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    form = dict(request.form)
    try:
        with _fetcher() as fetcher:
            preview = service.preview_link(fetcher, form.get("lien", ""))
        article = service.add_manual_article(get_db(), newsletter.id, preview, form, _brand_list())
    except LinkError as exc:
        return _add_article_page(newsletter, step=1, form=form, error=str(exc), status=400)
    except FormError as exc:
        return _add_article_page(newsletter, step=2, form=form, error=str(exc), status=400)
    flash(f"Article ajouté : « {article.title} ».", "success")
    return redirect(
        url_for("review.month", month=month, tab=_tab_of(article)) + f"#article-{article.id}"
    )


# --------------------------------------------------------------------------- franchisés


@bp.post("/<month>/franchises/<int:franchisee_id>")
def save_franchisee(month: str, franchisee_id: int) -> ResponseReturnValue:
    """Enregistre la carte d'un franchisé (marqué « modifié » : la détection n'y touche plus)."""
    newsletter = _newsletter(month)
    fiche = _franchisee(newsletter, franchisee_id)
    try:
        franchisees.update(get_db(), service.apply_franchisee_form(fiche, request.form))
    except FormError as exc:
        flash(f"Franchisé non enregistré : {exc}", "error")
    else:
        flash("Franchisé enregistré.", "success")
    return _back(month, "franchises", f"franchise-{franchisee_id}")


@bp.post("/<month>/franchises/<int:franchisee_id>/valider")
def validate_franchisee(month: str, franchisee_id: int) -> ResponseReturnValue:
    """Valide ou invalide un franchisé (bouton rapide)."""
    newsletter = _newsletter(month)
    _franchisee(newsletter, franchisee_id)
    valid = request.form.get("valeur") == "1"
    franchisees.set_validated(get_db(), franchisee_id, valid)
    flash("Franchisé validé." if valid else "Validation retirée.", "success")
    return _back(month, "franchises", f"franchise-{franchisee_id}")


@bp.post("/<month>/franchises/<int:franchisee_id>/deplacer")
def move_franchisee(month: str, franchisee_id: int) -> ResponseReturnValue:
    """Monte ou descend un franchisé."""
    newsletter = _newsletter(month)
    fiche = _franchisee(newsletter, franchisee_id)
    if not service.move_franchisee(get_db(), fiche, request.form.get("sens", "")):
        flash("Le franchisé est déjà en tête ou en fin de liste.", "warning")
    return _back(month, "franchises", f"franchise-{franchisee_id}")


@bp.route("/<month>/franchises/<int:franchisee_id>/supprimer", methods=["GET", "POST"])
def delete_franchisee(month: str, franchisee_id: int) -> ResponseReturnValue:
    """Confirmation (GET) puis retrait (POST) d'un franchisé."""
    newsletter = _newsletter(month)
    fiche = _franchisee(newsletter, franchisee_id)
    if request.method == "GET":
        return render_template(
            "review/confirm_delete.html",
            month=month,
            what="ce franchisé",
            label=fiche.name,
            action=url_for("review.delete_franchisee", month=month, franchisee_id=franchisee_id),
            cancel=url_for("review.month", month=month, tab="franchises")
            + f"#franchise-{franchisee_id}",
            note="Une suggestion de la détection supprimée ne sera pas reproposée.",
        )
    service.remove_franchisee(get_db(), fiche)
    flash(f"Franchisé supprimé : {fiche.name}.", "success")
    return _back(month, "franchises")


@bp.route("/<month>/ajouter-franchise", methods=["GET", "POST"])
def add_franchisee(month: str) -> ResponseReturnValue:
    """Ajout manuel d'un franchisé (lien source obligatoire et vérifié)."""
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    form: dict[str, str] = {"valider": "on"}
    error = None
    if request.method == "POST":
        form = dict(request.form)
        try:
            with _fetcher() as fetcher:
                fiche = service.add_manual_franchisee(get_db(), newsletter.id, form, fetcher)
        except FormError as exc:
            error = str(exc)
        else:
            flash(f"Franchisé ajouté : {fiche.name}.", "success")
            return redirect(
                url_for("review.month", month=month, tab="franchises") + f"#franchise-{fiche.id}"
            )
    return (
        render_template(
            "review/add_franchisee.html",
            newsletter=newsletter,
            month_label=month_label(newsletter.month),
            form=form,
            error=error,
        ),
        400 if error else 200,
    )
