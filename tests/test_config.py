"""Tests de la configuration."""

from __future__ import annotations

import dataclasses
import logging
import sys
from pathlib import Path

import pytest

from news_franchise.config import (
    DATA_SUBDIRS,
    ConfigError,
    Settings,
    default_data_dir,
    ensure_data_dir,
    load_settings,
)
from news_franchise.logging_setup import configure_logging


def test_defaults(tmp_path: Path) -> None:
    env = {"LOCALAPPDATA": str(tmp_path), "XDG_DATA_HOME": str(tmp_path)}
    settings = load_settings(env)

    expected_name = "NewsFranchise" if sys.platform == "win32" else "news-franchise"
    assert settings.data_dir == (tmp_path / expected_name).resolve()
    assert settings.host == "127.0.0.1"
    assert settings.port == 5000
    assert settings.debug is False
    assert settings.open_browser is True
    assert settings.log_level == "INFO"


def test_default_data_dir_windows(tmp_path: Path) -> None:
    env = {"LOCALAPPDATA": str(tmp_path)}
    assert default_data_dir(env, platform="win32") == tmp_path / "NewsFranchise"


def test_default_data_dir_linux_without_xdg() -> None:
    expected = Path.home() / ".local" / "share" / "news-franchise"
    assert default_data_dir({}, platform="linux") == expected


def test_env_overrides(tmp_path: Path) -> None:
    env = {
        "NF_DATA_DIR": str(tmp_path / "custom"),
        "NF_PORT": "8123",
        "NF_DEBUG": "true",
        "NF_OPEN_BROWSER": "non",
        "NF_LOG_LEVEL": "debug",
    }
    settings = load_settings(env)

    assert settings.data_dir == (tmp_path / "custom").resolve()
    assert settings.port == 8123
    assert settings.debug is True
    assert settings.open_browser is False
    assert settings.log_level == "DEBUG"


def test_empty_values_use_defaults(tmp_path: Path) -> None:
    env = {"NF_DATA_DIR": str(tmp_path), "NF_PORT": "", "NF_DEBUG": "  "}
    settings = load_settings(env)
    assert settings.port == 5000
    assert settings.debug is False


@pytest.mark.parametrize("port", ["abc", "80", "70000", "5000.5"])
def test_invalid_port(tmp_path: Path, port: str) -> None:
    with pytest.raises(ValueError, match="NF_PORT"):
        load_settings({"NF_DATA_DIR": str(tmp_path), "NF_PORT": port})


@pytest.mark.parametrize("name", ["NF_DEBUG", "NF_OPEN_BROWSER"])
def test_invalid_bool(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError, match=name):
        load_settings({"NF_DATA_DIR": str(tmp_path), name: "peut-être"})


def test_invalid_log_level(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="NF_LOG_LEVEL"):
        load_settings({"NF_DATA_DIR": str(tmp_path), "NF_LOG_LEVEL": "BAVARD"})


def test_data_subdirs_created(tmp_path: Path) -> None:
    data_dir = tmp_path / "nouveau" / "dossier"
    load_settings({"NF_DATA_DIR": str(data_dir)})
    for name in DATA_SUBDIRS:
        assert (data_dir / name).is_dir()


def test_data_dir_not_writable(tmp_path: Path) -> None:
    # Un fichier à la place du dossier : la création des sous-dossiers échoue.
    blocker = tmp_path / "fichier"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(ConfigError, match="accessible en écriture"):
        ensure_data_dir(blocker)


def test_settings_immutable(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.port = 6000  # type: ignore[misc]


def test_host_is_always_localhost(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        Settings(data_dir=tmp_path, host="0.0.0.0")


def test_configure_logging_writes_in_data_dir(settings: Settings) -> None:
    log_path = configure_logging(settings)
    try:
        logging.getLogger("news_franchise.test").warning("\x1b[31mmessage de test\x1b[0m")
        for handler in logging.getLogger().handlers:
            handler.flush()
        content = log_path.read_text(encoding="utf-8")
        assert log_path.parent == settings.logs_dir
        assert "message de test" in content
        assert "\x1b[" not in content
    finally:
        root = logging.getLogger()
        for handler in list(root.handlers):
            if getattr(handler, "_news_franchise_handler", False):
                root.removeHandler(handler)
                handler.close()
