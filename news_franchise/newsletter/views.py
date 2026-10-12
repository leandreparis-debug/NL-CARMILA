"""Pages de la newsletter : aperçu d'un mois et écran « Thème » (lecture seule).

L'aperçu assemble les gabarits communs (templates/newsletter/_*.html) avec medium="print" :
c'est la mise en page qui servira aux exports. Tout ce qui est calculé (QR codes, adresses
des photos, variables CSS du thème) est préparé ici ; les gabarits ne font qu'afficher.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, abort, current_app, render_template, send_file, url_for
from flask.typing import ResponseReturnValue
from markupsafe import Markup

from news_franchise.config import Settings
from news_franchise.db.connection import get_db
from news_franchise.models import validate_month
from news_franchise.newsletter.dates import format_month
from news_franchise.newsletter.qr import qr_svg
from news_franchise.newsletter.theme import THEME_FILE, Theme, ThemeError, load_theme
from news_franchise.newsletter.view import (
    OPPORTUNITY_LABEL,
    EmptyNewsletterError,
    NewsletterNotFoundError,
    NewsletterView,
    build_newsletter_view,
)

bp = Blueprint("newsletter", __name__)


def _settings() -> Settings:
    """Paramètres de l'application."""
    return current_app.config["NF_SETTINGS"]


def _theme_file() -> Path:
    """Fichier de thème (modifiable par les tests via NF_THEME_FILE)."""
    return Path(current_app.config.get("NF_THEME_FILE", THEME_FILE))


def qr_cache_dir(settings: Settings) -> Path:
    """Dossier de cache des QR codes : <données>/exports/qr."""
    return settings.exports_dir / "qr"


def newsletter_context(view: NewsletterView, theme: Theme, settings: Settings, medium: str) -> dict:
    """Variables communes aux gabarits de la newsletter.

    qr : URL → SVG en ligne (produit ici, depuis des URL déjà validées http/https) ;
    photo_src : nom de photo → adresse de la photo servie par l'application.
    """
    cache = qr_cache_dir(settings)
    return {
        "view": view,
        "theme": theme,
        "medium": medium,
        "theme_css": Markup(theme.css_variables()),  # valeurs validées au chargement
        "qr": {url: Markup(qr_svg(url, cache)) for url in view.article_urls},  # SVG généré ici
        "photo_src": {
            name: url_for("content.photo_file", file_name=name) for name in view.photo_files
        },
        "logo_src": url_for("newsletter.logo"),
        "opportunity_label": OPPORTUNITY_LABEL,
    }


def _theme_error_page(exc: ThemeError) -> ResponseReturnValue:
    """Page d'erreur claire quand config/theme.yaml est invalide."""
    return (
        render_template(
            "error.html",
            title="Thème invalide",
            code=500,
            message=f"{exc} Corrigez le fichier, puis rechargez la page.",
            back_url=url_for("newsletter.theme"),
        ),
        500,
    )


@bp.get("/newsletters/<month>/apercu")
def preview(month: str) -> ResponseReturnValue:
    """Aperçu de la newsletter du mois, mise en page « impression » (≈ 800 px, fond blanc)."""
    try:
        month = validate_month(month)
    except ValueError:
        abort(404)
    try:
        theme = load_theme(_theme_file())
    except ThemeError as exc:
        return _theme_error_page(exc)
    settings = _settings()
    try:
        view = build_newsletter_view(get_db(), month, settings, theme)
    except NewsletterNotFoundError:
        abort(404)
    except EmptyNewsletterError as exc:
        return render_template(
            "newsletter/preview_empty.html",
            month=month,
            month_label=format_month(month),
            message=str(exc),
        )
    return render_template(
        "newsletter/preview.html", **newsletter_context(view, theme, settings, "print")
    )


@bp.get("/theme")
def theme() -> ResponseReturnValue:
    """Écran « Thème » en lecture seule : couleurs, polices, logo, contrastes, fichier."""
    path = _theme_file()
    try:
        current = load_theme(path)
    except ThemeError as exc:
        return render_template("newsletter/theme.html", theme=None, error=str(exc), path=path)
    return render_template(
        "newsletter/theme.html",
        theme=current,
        error=None,
        path=path,
        checks=current.contrast_checks(),
        warnings=current.warnings(),
    )


@bp.get("/theme/logo")
def logo() -> ResponseReturnValue:
    """Logo du thème (fichier indiqué dans config/theme.yaml)."""
    try:
        current = load_theme(_theme_file())
    except ThemeError:
        abort(404)
    return send_file(current.logo, max_age=0)
