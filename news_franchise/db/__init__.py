"""Accès à la base SQLite locale : connexion, migrations versionnées, intégration Flask."""

from news_franchise.db.connection import (
    DatabaseError,
    MigrationError,
    get_connection,
    init_db,
    transaction,
)

__all__ = ["DatabaseError", "MigrationError", "get_connection", "init_db", "transaction"]
