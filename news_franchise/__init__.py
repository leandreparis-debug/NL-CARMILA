"""News Franchise : préparation de la newsletter interne mensuelle de Carmila Franchise."""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import Forbidden, InternalServerError, NotFound

from news_franchise.bootstrap import prepare_database
from news_franchise.collect.views import bp as collect_bp
from news_franchise.config import Settings, load_settings
from news_franchise.content.views import bp as content_bp
from news_franchise.dates import format_month_fr
from news_franchise.db import connection as db_connection
from news_franchise.newsletter.views import bp as newsletter_bp
from news_franchise.review.views import bp as review_bp
from news_franchise.security import init_security
from news_franchise.version import __version__

__all__ = ["__version__", "create_app"]

logger = logging.getLogger(__name__)

# Boutons de la page d'accueil : (libellé, route Flask) ; route None = pas encore disponible.
FEATURES: tuple[tuple[str, str | None], ...] = (
    ("Collecter la veille", "collect.index"),
    ("Relire", "review.index"),
    ("Contenu interne", "content.start"),
    ("Exporter", "newsletter.exports"),
    ("Thème", "newsletter.theme"),
)


def create_app(settings: Settings | None = None, brands_file: Path | None = None) -> Flask:
    """Crée et configure l'application Flask.

    Si settings est None, la configuration est chargée depuis l'environnement et .env.
    Les paramètres sont disponibles dans app.config["NF_SETTINGS"].

    Au démarrage : applique les migrations manquantes de la base, puis synchronise le
    référentiel des enseignes (brands_file, par défaut config/enseignes.yaml). Lève
    MigrationError ou BrandCatalogError (messages en français) si l'un des deux échoue.
    Chaque requête dispose ensuite de sa propre connexion (news_franchise.db.connection.get_db).
    """
    if settings is None:
        settings = load_settings()

    prepare_database(settings, brands_file)

    app = Flask(__name__)
    app.config["NF_SETTINGS"] = settings
    app.config["DEBUG"] = settings.debug
    db_connection.init_app(app)
    init_security(app, settings)
    app.register_blueprint(collect_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(content_bp)
    app.register_blueprint(newsletter_bp)

    @app.context_processor
    def inject_globals() -> dict[str, object]:
        """Variables communes à tous les gabarits."""
        return {"app_version": __version__}

    @app.get("/")
    def index() -> ResponseReturnValue:
        """Page d'accueil."""
        return render_template(
            "index.html",
            current_month=format_month_fr(date.today()),
            features=FEATURES,
        )

    @app.get("/health")
    def health() -> ResponseReturnValue:
        """État de l'application, pour vérifier qu'elle répond."""
        return jsonify(status="ok", version=__version__)

    @app.errorhandler(NotFound)
    def page_not_found(error: NotFound) -> ResponseReturnValue:
        """Page 404 en français."""
        return (
            render_template(
                "error.html",
                code=404,
                title="Page introuvable",
                message="La page demandée n'existe pas.",
            ),
            404,
        )

    @app.errorhandler(Forbidden)
    def forbidden(error: Forbidden) -> ResponseReturnValue:
        """Page 403 en français."""
        return (
            render_template(
                "error.html",
                code=403,
                title="Action refusée",
                message="Cette action doit être lancée depuis l'application News Franchise.",
            ),
            403,
        )

    @app.errorhandler(InternalServerError)
    def internal_error(error: InternalServerError) -> ResponseReturnValue:
        """Page 500 en français, sans trace technique."""
        # Flask a déjà journalisé la trace complète (logger "news_franchise") :
        # l'utilisateur ne voit qu'un message générique.
        return (
            render_template(
                "error.html",
                code=500,
                title="Erreur interne",
                message=(
                    "Une erreur inattendue s'est produite. "
                    "Le détail technique a été enregistré dans le journal de l'application."
                ),
            ),
            500,
        )

    return app
