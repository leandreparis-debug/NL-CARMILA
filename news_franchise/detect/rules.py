"""Chargement et validation de config/regles_detection.yaml et config/lieux_france.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from news_franchise.config import PROJECT_DIR, ConfigError
from news_franchise.detect.text import keep_length_apostrophes

DETECTION_RULES_FILE = PROJECT_DIR / "config" / "regles_detection.yaml"
PLACES_FILE = PROJECT_DIR / "config" / "lieux_france.yaml"
PLACEHOLDERS = ("{n}", "{ordinal}", "{unit}")


class DetectionRulesError(ConfigError):
    """Règles de détection ou fichier de lieux invalides (message en français)."""


@dataclass(frozen=True)
class OpportunityRules:
    """Listes du repère « opportunité »."""

    search_terms: tuple[str, ...]
    place_terms: tuple[str, ...]
    strong_terms: tuple[str, ...]
    exclusions: tuple[str, ...] = ()


@dataclass(frozen=True)
class FranchiseeRules:
    """Règles d'extraction des franchisés."""

    trigger_patterns: tuple[str, ...]
    store_units: tuple[str, ...]
    number_words: dict[str, int]
    ordinal_words: tuple[str, ...]
    company_markers: tuple[str, ...]
    company_suffixes: tuple[str, ...]
    name_stopwords: frozenset[str]
    compiled_triggers: tuple[re.Pattern[str], ...] = field(default=(), compare=False)

    @property
    def number_pattern(self) -> str:
        """Motif d'un nombre : chiffres ou nombre en lettres (« dix-sept » avant « dix »)."""
        words = sorted(self.number_words, key=len, reverse=True)
        return r"(?:\d{1,4}|" + "|".join(re.escape(w) for w in words) + ")"

    @property
    def ordinal_pattern(self) -> str:
        """Motif d'un rang : « 3e », « 3ème », « 3eme », « troisième »…"""
        words = sorted(self.ordinal_words, key=len, reverse=True)
        return r"(?:\d{1,3}\s?(?:e|è|ème|eme|er)|" + "|".join(re.escape(w) for w in words) + ")"

    @property
    def unit_pattern(self) -> str:
        """Motif d'un mot de store_units."""
        units = sorted(self.store_units, key=len, reverse=True)
        return "(?:" + "|".join(re.escape(u).replace(r"\ ", r"\s+") for u in units) + ")"


@dataclass(frozen=True)
class DetectionRules:
    """Ensemble des règles de détection."""

    opportunity: OpportunityRules
    franchisee: FranchiseeRules


@dataclass(frozen=True)
class Places:
    """Lieux reconnus : nom affiché → variantes écrites dans les articles."""

    regions: dict[str, tuple[str, ...]]
    departments: tuple[str, ...]
    cities: tuple[str, ...]

    def all_names(self) -> dict[str, str]:
        """Variante → nom affiché, pour toutes les catégories."""
        names: dict[str, str] = {}
        for city in self.cities:
            names.setdefault(city, city)
        for department in self.departments:
            names.setdefault(department, department)
        for region, aliases in self.regions.items():
            names.setdefault(region, region)
            for alias in aliases:
                names.setdefault(alias, region)
        return names


def _read(path: Path) -> Any:
    """Lit un fichier YAML (erreurs en français)."""
    if not path.is_file():
        raise DetectionRulesError(
            f"Fichier introuvable : {path}. Ce fichier fait partie du projet."
        )
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f", ligne {mark.line + 1}" if mark is not None else ""
        problem = getattr(exc, "problem", None) or exc
        raise DetectionRulesError(f"{path.name}{where} : YAML illisible ({problem}).") from exc


def _section(data: Any, key: str, where: str) -> dict[str, Any]:
    """Sous-bloc obligatoire."""
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, dict):
        raise DetectionRulesError(f"{where} : le bloc « {key}: » est absent ou invalide.")
    return value


def _strings(
    block: dict[str, Any], key: str, where: str, *, required: bool = True
) -> tuple[str, ...]:
    """Liste de textes non vides, sans doublon (comparaison sans casse)."""
    values = block.get(key)
    if values is None and not required:
        return ()
    if not isinstance(values, list) or (required and not values):
        raise DetectionRulesError(f"{where} : « {key} » doit être une liste non vide de textes.")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise DetectionRulesError(
                f"{where} : « {key} » contient une valeur vide ou invalide ({value!r}). "
                'Mettez les mots comme On, Oui, Non, Yes, No entre guillemets ("On").'
            )
        key_value = value.strip().casefold()
        if key_value in seen:
            raise DetectionRulesError(
                f"{where} : « {value.strip()} » est en double dans « {key} »."
            )
        seen.add(key_value)
        result.append(value.strip())
    return tuple(result)


def _check_keys(block: dict[str, Any], allowed: set[str], where: str) -> None:
    """Refuse les clés inconnues (fautes de frappe)."""
    unknown = sorted(set(block) - allowed)
    if unknown:
        raise DetectionRulesError(
            f"{where} : clé(s) inconnue(s) {', '.join(map(str, unknown))} "
            f"(clés possibles : {', '.join(sorted(allowed))})."
        )


def compile_trigger(pattern: str, rules: FranchiseeRules) -> re.Pattern[str]:
    """Compile un motif déclencheur après remplacement de {n}, {ordinal} et {unit}."""
    expanded = keep_length_apostrophes(pattern)
    expanded = expanded.replace("{n}", rules.number_pattern)
    expanded = expanded.replace("{ordinal}", rules.ordinal_pattern)
    expanded = expanded.replace("{unit}", rules.unit_pattern)
    expanded = expanded.replace(" ", r"\s+")
    return re.compile(r"(?<![\w])" + expanded + r"(?![\w])", re.IGNORECASE)


def load_detection_rules(path: Path = DETECTION_RULES_FILE) -> DetectionRules:
    """Lit et valide config/regles_detection.yaml.

    Lève DetectionRulesError avec un message clair (liste fautive, expression invalide).
    """
    data = _read(path)
    where = path.name
    if not isinstance(data, dict):
        raise DetectionRulesError(f"{where} : contenu invalide.")
    _check_keys(data, {"opportunity", "franchisee"}, where)

    opp = _section(data, "opportunity", where)
    opp_where = f"{where}, bloc opportunity"
    _check_keys(opp, {"search_terms", "place_terms", "strong_terms", "exclusions"}, opp_where)
    opportunity = OpportunityRules(
        search_terms=_strings(opp, "search_terms", opp_where),
        place_terms=_strings(opp, "place_terms", opp_where),
        strong_terms=_strings(opp, "strong_terms", opp_where),
        exclusions=_strings(opp, "exclusions", opp_where, required=False),
    )

    fra = _section(data, "franchisee", where)
    fra_where = f"{where}, bloc franchisee"
    _check_keys(
        fra,
        {
            "trigger_patterns",
            "store_units",
            "number_words",
            "ordinal_words",
            "company_markers",
            "company_suffixes",
            "name_stopwords",
        },
        fra_where,
    )
    numbers = fra.get("number_words")
    if (
        not isinstance(numbers, dict)
        or not numbers
        or not all(
            isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool) and v > 0
            for k, v in numbers.items()
        )
    ):
        raise DetectionRulesError(
            f"{fra_where} : « number_words » doit associer des mots à des nombres entiers "
            "(ex. « cinq: 5 »)."
        )
    franchisee = FranchiseeRules(
        trigger_patterns=_strings(fra, "trigger_patterns", fra_where),
        store_units=_strings(fra, "store_units", fra_where),
        number_words={k.strip().lower(): v for k, v in numbers.items()},
        ordinal_words=_strings(fra, "ordinal_words", fra_where),
        company_markers=_strings(fra, "company_markers", fra_where),
        company_suffixes=_strings(fra, "company_suffixes", fra_where),
        name_stopwords=frozenset(_strings(fra, "name_stopwords", fra_where)),
    )
    compiled: list[re.Pattern[str]] = []
    for pattern in franchisee.trigger_patterns:
        try:
            compiled.append(compile_trigger(pattern, franchisee))
        except re.error as exc:
            raise DetectionRulesError(
                f"{fra_where} : l'expression « {pattern} » de « trigger_patterns » est "
                f"invalide ({exc.msg})."
            ) from exc
    franchisee = FranchiseeRules(**{**franchisee.__dict__, "compiled_triggers": tuple(compiled)})
    return DetectionRules(opportunity=opportunity, franchisee=franchisee)


def load_places(path: Path = PLACES_FILE) -> Places:
    """Lit et valide config/lieux_france.yaml."""
    data = _read(path)
    where = path.name
    if not isinstance(data, dict):
        raise DetectionRulesError(f"{where} : contenu invalide.")
    _check_keys(data, {"regions", "departements", "villes"}, where)
    raw_regions = data.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise DetectionRulesError(f"{where} : « regions » doit être une liste non vide.")
    regions: dict[str, tuple[str, ...]] = {}
    for item in raw_regions:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            raise DetectionRulesError(f"{where} : chaque région doit avoir « name: ».")
        aliases = item.get("aliases") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            raise DetectionRulesError(
                f"{where} : « aliases » de {item['name']} doit être une liste."
            )
        regions[item["name"].strip()] = tuple(a.strip() for a in aliases if a.strip())
    return Places(
        regions=regions,
        departments=_strings(data, "departements", where),
        cities=_strings(data, "villes", where),
    )
