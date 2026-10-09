"""Fixtures communes : toutes les données de test restent dans tmp_path."""

from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from news_franchise import create_app
from news_franchise.config import Settings, load_settings


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """Dossier de données isolé dans tmp_path."""
    return tmp_path / "data"


@pytest.fixture
def settings(data_dir: Path) -> Settings:
    """Paramètres de test pointant vers le dossier temporaire."""
    return load_settings({"NF_DATA_DIR": str(data_dir), "NF_OPEN_BROWSER": "false"})


@pytest.fixture
def app(settings: Settings) -> Flask:
    """Application Flask de test."""
    return create_app(settings)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Client HTTP de test."""
    return app.test_client()
