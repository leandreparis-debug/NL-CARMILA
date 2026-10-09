"""Tests de l'application web."""

from __future__ import annotations

from datetime import date

from flask import Flask
from flask.testing import FlaskClient

from news_franchise import __version__, create_app
from news_franchise.config import Settings
from news_franchise.dates import format_month_fr


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
