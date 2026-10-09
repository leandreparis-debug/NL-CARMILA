"""Configuration de la journalisation : fichier rotatif dans le dossier de données + console."""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

from news_franchise.config import Settings

LOG_FILE_NAME = "news_franchise.log"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s : %(message)s"
MAX_LOG_BYTES = 1_000_000
LOG_BACKUP_COUNT = 5

_HANDLER_MARKER = "_news_franchise_handler"
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


class PlainFormatter(logging.Formatter):
    """Formateur qui retire les codes couleur ANSI (ajoutés par Werkzeug) pour le fichier."""

    def format(self, record: logging.LogRecord) -> str:
        """Formate l'enregistrement sans séquences de couleur."""
        return _ANSI_ESCAPE.sub("", super().format(record))


def configure_logging(settings: Settings) -> Path:
    """Configure le logger racine et renvoie le chemin du fichier de log.

    La fonction est idempotente : un nouvel appel remplace les gestionnaires
    installés précédemment au lieu de les dupliquer.
    """
    log_path = settings.logs_dir / LOG_FILE_NAME
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARKER, False):
            root.removeHandler(handler)
            handler.close()

    file_handler = RotatingFileHandler(
        log_path, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(PlainFormatter(LOG_FORMAT))
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
    for handler in (file_handler, console_handler):
        setattr(handler, _HANDLER_MARKER, True)
        root.addHandler(handler)

    root.setLevel(settings.log_level)
    return log_path
