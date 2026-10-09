"""Repérage d'une ville, d'un département ou d'une région dans une phrase."""

from __future__ import annotations

import re

from news_franchise.detect.rules import Places
from news_franchise.detect.text import keep_length_apostrophes, strip_accents_keep_length

# « à », « au », « aux », « en », « dans le/la/les/l' », éventuellement suivis de « (la) région ».
_PREPOSITION = (
    r"(?<![\w])(?i:a|au|aux|en|dans\s+(?:le|la|les)|dans\s+l')\s*(?i:(?:la\s+)?region\s+)?"
)


def _normalize(text: str) -> str:
    """Forme de comparaison à longueur constante : sans accents, apostrophes unifiées."""
    return strip_accents_keep_length(keep_length_apostrophes(text))


def _variant_pattern(name: str) -> str:
    """Motif d'un nom de lieu (espaces souples)."""
    return re.escape(_normalize(name)).replace(r"\ ", r"\s+")


class PlaceMatcher:
    """Trouve « à Lyon », « en Occitanie », « dans le Rhône »… (nom avec majuscule)."""

    def __init__(self, places: Places) -> None:
        """Compile un motif pour tous les lieux connus (du plus long au plus court)."""
        self._canonical: dict[str, str] = {}
        variants: list[str] = []
        after_au: list[str] = []  # « Le Mans » → « au Mans », « du Mans »
        for variant, canonical in places.all_names().items():
            key = _normalize(variant)
            self._canonical[key] = canonical
            variants.append(variant)
            if variant.startswith("Le "):
                short = variant[3:]
                self._canonical[_normalize(short)] = canonical
                after_au.append(short)
        self._names = frozenset(_normalize(v).casefold() for v in self._canonical)
        alternation = "|".join(_variant_pattern(v) for v in sorted(variants, key=len, reverse=True))
        self._pattern = re.compile(_PREPOSITION + f"(?P<place>{alternation})(?![\\w'-])")
        self._pattern_au = (
            re.compile(
                r"(?<![\w])(?i:au|du)\s+(?P<place>"
                + "|".join(_variant_pattern(v) for v in after_au)
                + r")(?![\w'-])"
            )
            if after_au
            else None
        )

    def find(self, sentence: str) -> str | None:
        """Premier lieu trouvé dans la phrase (nom affiché), ou None."""
        text = _normalize(sentence)
        hits = [m for p in (self._pattern, self._pattern_au) if p for m in p.finditer(text)]
        if not hits:
            return None
        first = min(hits, key=lambda m: m.start())
        key = re.sub(r"\s+", " ", first.group("place"))
        return self._canonical.get(key)

    def is_place_name(self, text: str) -> bool:
        """Vrai si le texte (ou l'un de ses mots) est un nom de lieu connu."""
        normalized = _normalize(text).casefold()
        if normalized in self._names:
            return True
        return any(token in self._names for token in normalized.split())
