"""Tests du référentiel des enseignes."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from news_franchise.brand_catalog import (
    BRANDS_FILE,
    BrandCatalogError,
    load_brand_catalog,
    parse_brand_catalog,
    slugify,
)
from news_franchise.config import ConfigError
from news_franchise.repositories import brands
from news_franchise.sources.candidates import BRANDS


def test_project_catalog_is_valid() -> None:
    entries = load_brand_catalog(BRANDS_FILE)
    assert [e.name for e in entries] == list(BRANDS)  # mêmes 15 enseignes que la veille


def test_sync_creates_15_brands(conn: sqlite3.Connection) -> None:
    result = brands.sync_from_yaml(conn, BRANDS_FILE)
    assert len(result.added) == 15
    all_brands = brands.list_all(conn)
    assert len(all_brands) == 15 and all(b.tracked for b in all_brands)
    otacos = brands.get_by_name(conn, "O'Tacos")
    assert otacos is not None
    assert otacos.slug == "o-tacos"
    assert otacos.sector == "Restauration rapide"
    assert otacos.aliases == ["OTacos", "O Tacos", "O’Tacos"]
    assert brands.get_by_slug(conn, "crepe-touch") is not None
    # Deuxième synchronisation : rien ne change.
    assert brands.sync_from_yaml(conn, BRANDS_FILE) == brands.BrandSyncResult()


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "enseignes.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_removed_brand_becomes_untracked(conn: sqlite3.Connection, tmp_path: Path) -> None:
    brands.sync_from_yaml(conn, BRANDS_FILE)
    text = BRANDS_FILE.read_text(encoding="utf-8")
    reduced = text.replace(
        "  - name: Chopstix\n    sector: Restauration rapide\n    aliases: []\n", ""
    )
    reduced = reduced.replace('sector: "À compléter"', "sector: Mode et accessoires")
    assert reduced != text

    result = brands.sync_from_yaml(conn, _write(tmp_path, reduced))

    assert result.untracked == ["Chopstix"]
    assert result.updated == ["Mira Mira"]
    chopstix = brands.get_by_name(conn, "Chopstix")
    assert chopstix is not None and chopstix.tracked is False  # jamais supprimée
    assert len(brands.list_all(conn)) == 15
    assert len(brands.list_all(conn, tracked_only=True)) == 14
    mira = brands.get_by_name(conn, "Mira Mira")
    assert mira is not None and mira.sector == "Mode et accessoires"

    # Remise dans le YAML : de nouveau suivie.
    result = brands.sync_from_yaml(conn, BRANDS_FILE)
    assert "Chopstix" in result.updated
    assert brands.get_by_name(conn, "Chopstix").tracked is True  # type: ignore[union-attr]


def test_duplicate_name_is_rejected(conn: sqlite3.Connection, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "brands:\n"
        "  - name: Pokawa\n"
        "    sector: Restauration rapide\n"
        "  - name: pokawa\n"
        "    sector: Autre\n",
    )
    with pytest.raises(BrandCatalogError) as excinfo:
        brands.sync_from_yaml(conn, path)
    message = str(excinfo.value)
    assert "ligne 4" in message and "pokawa" in message and "doublon" in message
    assert brands.list_all(conn) == []  # base non modifiée


def test_duplicate_alias_between_brands_is_rejected() -> None:
    text = (
        "brands:\n"
        "  - name: Dunkin' Donuts\n"
        "    aliases: [Dunkin]\n"
        "  - name: Dunkin Coffee\n"
        '    aliases: ["DUNKIN"]\n'
    )
    with pytest.raises(
        BrandCatalogError, match=r"ligne 4 \(« Dunkin Coffee »\).*l'alias « DUNKIN »"
    ):
        parse_brand_catalog(text)


def test_variants_of_same_brand_are_allowed() -> None:
    entries = parse_brand_catalog(
        'brands:\n  - name: G La Dalle\n    aliases: ["G la Dalle", "GLaDalle"]\n'
    )
    assert entries[0].aliases == ("G la Dalle", "GLaDalle")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("brands:\n  - sector: Chocolaterie\n", "ligne 2 (enseigne n°1) : le nom"),
        ('brands:\n  - name: "  "\n', "le nom de l'enseigne est obligatoire"),
        ("brands:\n  - name: A\n    secteur: X\n", "champ(s) inconnu(s) secteur"),
        ("brands:\n  - name: A\n    aliases: B\n", "« aliases » doit être une liste"),
        ("enseignes: []\n", "liste « brands: » non vide"),
        ("brands:\n  - name: [A\n", "YAML illisible"),
    ],
)
def test_invalid_catalog_messages(text: str, expected: str) -> None:
    with pytest.raises(BrandCatalogError) as excinfo:
        parse_brand_catalog(text)
    assert expected in str(excinfo.value)
    assert isinstance(excinfo.value, ConfigError)


def test_slugify() -> None:
    assert slugify("Crêpe Touch") == "crepe-touch"
    assert slugify("Dunkin' Donuts") == "dunkin-donuts"
