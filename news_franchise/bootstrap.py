"""Préparation de la base au démarrage (application web et outils en ligne de commande)."""

from __future__ import annotations

import logging
from contextlib import closing
from pathlib import Path

from news_franchise.brand_catalog import BRANDS_FILE
from news_franchise.config import Settings
from news_franchise.db import connection as db_connection
from news_franchise.repositories import brands

logger = logging.getLogger(__name__)


def prepare_database(settings: Settings, brands_file: Path | None = None) -> int:
    """Applique les migrations manquantes puis synchronise le référentiel des enseignes.

    Renvoie la version du schéma. Lève MigrationError ou BrandCatalogError (messages en
    français) si l'une des deux étapes échoue.
    """
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
    return version
