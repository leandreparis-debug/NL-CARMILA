"""News Franchise : préparation de la newsletter interne mensuelle de Carmila Franchise."""

from __future__ import annotations

import logging
from contextlib import closing
from datetime import date
from pathlib import Path

from flask import Flask, jsonify, render_template
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import InternalServerError, NotFound

from news_franchise.brand_catalog import BRANDS_FILE
from news_franchise.config import Settings, load_settings
from news_franchise.dates import format_month_fr
from news_franchise.db import connection as db_connection
from news_franchise.repositories import brands

__version__ = "0.1.0"

__all__ = ["__version__", "create_app"]

logger = logging.getLogger(__name__)

# Fonctions prévues aux étapes suivantes (boutons désactivés pour l'instant).
UPCOMING_FEATURES = (
    "Collecter la veille",
    "Relire",
    "Contenu interne",
    "Exporter",
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

    version = db_connection.init_db(settings)
    with closing(db_connection.get_connection(settings)) as conn:
        sync = brands.sync_from_yaml(conn, brands_file or BRANDS_FILE)
    logger.info(
        "Base %s (schéma v%d) ; enseignes ajoutées : %d, mises à jour : %d, plus suivies : %d",
        db_connection.db_path(settings),
        version,
        len(sync.added),
        len(sync.updated),
        len(sync.untracked),
    )

    app = Flask(__name__)
    app.config["NF_SETTINGS"] = settings
    app.config["DEBUG"] = settings.debug
    db_connection.init_app(app)

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
            features=UPCOMING_FEATURES,
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
