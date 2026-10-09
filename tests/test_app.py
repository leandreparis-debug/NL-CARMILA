"""Tests de l'application web."""

from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from flask import Flask, g
from flask.testing import FlaskClient

from news_franchise import __version__, create_app
from news_franchise.brand_catalog import BrandCatalogError
from news_franchise.config import Settings
from news_franchise.dates import format_month_fr
from news_franchise.db.connection import (
    current_version,
    db_path,
    get_connection,
    get_db,
    list_migrations,
)
from news_franchise.repositories import brands


def test_index(client: FlaskClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "News Franchise" in html
    assert format_month_fr(date.today()) in html
    for label in ("Collecter la veille", "Relire", "Contenu interne", "Exporter"):
        assert label in html
    assert "disabled" in html


def test_health(client: FlaskClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "version": __version__}


def test_404_page_in_french(client: FlaskClient) -> None:
    response = client.get("/cette-page-n-existe-pas")
    assert response.status_code == 404
    html = response.get_data(as_text=True)
    assert "Page introuvable" in html
    assert "La page demandée" in html


def test_500_page_hides_traceback(settings: Settings) -> None:
    app: Flask = create_app(settings)

    @app.get("/boom")
    def boom() -> str:
        raise RuntimeError("détail secret de l'erreur")

    response = app.test_client().get("/boom")
    assert response.status_code == 500
    html = response.get_data(as_text=True)
    assert "Erreur interne" in html
    assert "Traceback" not in html
    assert "RuntimeError" not in html
    assert "détail secret" not in html


def test_settings_stored_in_app(app: Flask, settings: Settings) -> None:
    assert app.config["NF_SETTINGS"] is settings


def test_format_month_fr() -> None:
    assert format_month_fr(date(2026, 10, 9)) == "Octobre 2026"
    assert format_month_fr(date(2026, 8, 1)) == "Août 2026"


def test_app_creates_database_with_brands(app: Flask, settings: Settings) -> None:
    assert db_path(settings).is_file()
    with closing(get_connection(settings)) as conn:
        assert current_version(conn) == list_migrations()[-1].version
        assert len(brands.list_all(conn, tracked_only=True)) == 15


def test_invalid_brands_file_prevents_startup(settings: Settings, tmp_path: Path) -> None:
    bad = tmp_path / "enseignes.yaml"
    bad.write_text("brands:\n  - name: A\n  - name: a\n", encoding="utf-8")
    with pytest.raises(BrandCatalogError, match="ligne 3"):
        create_app(settings, brands_file=bad)


def test_one_connection_per_request_closed_at_teardown(app: Flask) -> None:
    with app.app_context():
        conn = get_db()
        assert get_db() is conn
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert "db" in g
    with pytest.raises(Exception, match="closed"):
        conn.execute("SELECT 1")
