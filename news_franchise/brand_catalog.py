"""Chargement et validation du référentiel des enseignes (config/enseignes.yaml)."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from news_franchise.config import PROJECT_DIR, ConfigError

BRANDS_FILE = PROJECT_DIR / "config" / "enseignes.yaml"
ALLOWED_KEYS = frozenset({"name", "sector", "aliases"})


class BrandCatalogError(ConfigError):
    """Référentiel des enseignes invalide (message en français, avec la ligne fautive)."""


@dataclass(frozen=True)
class BrandEntry:
    """Enseigne telle que décrite dans le fichier YAML."""

    name: str
    sector: str = ""
    aliases: tuple[str, ...] = field(default_factory=tuple)
    line: int = 0  # ligne du fichier, pour les messages d'erreur


def slugify(text: str) -> str:
    """Identifiant ASCII en minuscules (« Crêpe Touch » → « crepe-touch »)."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")


def _normalize_key(text: str) -> str:
    """Forme de comparaison des noms et alias (casse, accents, apostrophes typographiques)."""
    text = text.replace("’", "'").casefold()
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").strip()


def _entry_lines(text: str) -> list[int]:
    """Numéro de ligne (à partir de 1) de chaque élément de la liste « brands »."""
    root = yaml.compose(text)
    if not isinstance(root, yaml.MappingNode):
        return []
    for key, value in root.value:
        if getattr(key, "value", None) == "brands" and isinstance(value, yaml.SequenceNode):
            return [item.start_mark.line + 1 for item in value.value]
    return []


def parse_brand_catalog(text: str, source: str = "config/enseignes.yaml") -> list[BrandEntry]:
    """Analyse et valide le contenu YAML du référentiel.

    Règles : liste « brands » non vide ; nom obligatoire ; secteur texte ; alias liste de
    textes ; un nom ou alias ne peut désigner qu'une seule enseigne (comparaison sans
    tenir compte de la casse, des accents ni du type d'apostrophe).
    Lève BrandCatalogError avec la ligne et l'enseigne fautives.
    """
    try:
        data = yaml.safe_load(text)
        lines = _entry_lines(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f", ligne {mark.line + 1}" if mark is not None else ""
        problem = getattr(exc, "problem", None) or str(exc)
        raise BrandCatalogError(f"{source}{where} : YAML illisible ({problem}).") from exc

    if not isinstance(data, dict) or not isinstance(data.get("brands"), list) or not data["brands"]:
        raise BrandCatalogError(
            f"{source} : le fichier doit contenir une liste « brands: » non vide."
        )

    entries: list[BrandEntry] = []
    seen: dict[str, str] = {}  # forme normalisée → description de la première occurrence
    for index, item in enumerate(data["brands"]):
        line = lines[index] if index < len(lines) else 0
        label = f"enseigne n°{index + 1}"
        where = f"{source}, ligne {line} ({label})" if line else f"{source} ({label})"
        if not isinstance(item, dict):
            raise BrandCatalogError(f"{where} : chaque enseigne doit avoir « name: ».")
        unknown = sorted(set(item) - ALLOWED_KEYS)
        if unknown:
            raise BrandCatalogError(
                f"{where} : champ(s) inconnu(s) {', '.join(map(str, unknown))} "
                "(champs possibles : name, sector, aliases)."
            )
        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            raise BrandCatalogError(f"{where} : le nom de l'enseigne est obligatoire.")
        name = name.strip()
        where = f"{source}, ligne {line} (« {name} »)" if line else f"{source} (« {name} »)"
        sector = item.get("sector", "")
        if sector is None:
            sector = ""
        if not isinstance(sector, str):
            raise BrandCatalogError(f"{where} : le secteur doit être un texte.")
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list) or not all(
            isinstance(a, str) and a.strip() for a in aliases
        ):
            raise BrandCatalogError(f"{where} : « aliases » doit être une liste de textes.")
        aliases = [a.strip() for a in aliases]
        if not slugify(name):
            raise BrandCatalogError(f"{where} : le nom doit contenir des lettres ou chiffres.")

        # Les variantes d'une même enseigne (casse, accents, apostrophe typographique)
        # sont permises ; un même nom ou alias ne peut pas désigner deux enseignes.
        own_keys: dict[str, str] = {}
        for value, kind in [(name, "le nom"), *((a, "l'alias") for a in aliases)]:
            key = _normalize_key(value)
            if key in seen:
                raise BrandCatalogError(
                    f"{where} : doublon, {kind} « {value} » est déjà utilisé ({seen[key]})."
                )
            own_keys.setdefault(key, f"par « {name} »" + (f", ligne {line}" if line else ""))
        seen.update(own_keys)
        entries.append(
            BrandEntry(name=name, sector=sector.strip(), aliases=tuple(aliases), line=line)
        )

    slugs = [slugify(e.name) for e in entries]
    for entry, slug in zip(entries, slugs, strict=True):
        if slugs.count(slug) > 1:
            raise BrandCatalogError(
                f"{source}, ligne {entry.line} (« {entry.name} ») : ce nom est trop proche "
                f"d'une autre enseigne (même identifiant « {slug} »)."
            )
    return entries


def load_brand_catalog(path: Path = BRANDS_FILE) -> list[BrandEntry]:
    """Lit et valide le fichier du référentiel des enseignes."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BrandCatalogError(
            f"Impossible de lire le référentiel des enseignes {path} : {exc.strerror or exc}."
        ) from exc
    try:
        source = str(path.relative_to(PROJECT_DIR))
    except ValueError:
        source = str(path)
    return parse_brand_catalog(text, source=source)
