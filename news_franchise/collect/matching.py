"""Détection des enseignes suivies et des termes de développement en franchise."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from news_franchise.collect.text import fold
from news_franchise.models import RUBRIC_BRAND_NEWS, RUBRIC_NEW_FRANCHISES, Brand

# Limites de mot : ni lettre/chiffre avant, ni lettre/chiffre après.
_BEFORE = r"(?<![\w])"
_AFTER = r"(?![\w])"


def _phrase_pattern(phrase: str, *, case_sensitive: bool, plural: bool = False) -> str:
    """Motif regex d'une expression (sur texte déjà replié par fold).

    Les espaces de l'expression acceptent n'importe quel espacement ; l'apostrophe est
    facultative (« O'Tacos » trouve aussi « OTacos » et « O Tacos »). case_sensitive :
    la première lettre doit être en majuscule, le reste est insensible à la casse.
    """
    folded = fold(phrase, keep_case=case_sensitive)
    parts: list[str] = []
    for char in folded:
        if char == " ":
            parts.append(r"\s+")
        elif char == "'":
            parts.append(r"(?:'\s*|\s+)?")
        else:
            parts.append(re.escape(char))
    if case_sensitive and folded and folded[0].isalpha():
        head, tail = parts[0], "".join(parts[1:])
        body = f"{head}(?i:{tail})" if tail else head
    else:
        body = "".join(parts)
        if case_sensitive:
            body = f"(?i:{body})"
    if plural:
        body += r"(?:s|x)?"
    return _BEFORE + body + _AFTER


@dataclass(frozen=True)
class BrandMatch:
    """Enseigne trouvée et position de la première occurrence."""

    brand: Brand
    position: int


class BrandMatcher:
    """Repère les enseignes suivies (nom ou alias) dans un texte.

    Ignore la casse, les accents et les variantes d'apostrophe ; respecte les limites de
    mots. Pour une enseigne case_sensitive, la majuscule initiale est exigée.
    """

    def __init__(self, brands: Sequence[Brand]) -> None:
        """Compile un motif par enseigne suivie (tracked)."""
        self._patterns: list[tuple[Brand, re.Pattern[str], bool]] = []
        for brand in brands:
            if not brand.tracked:
                continue
            variants = sorted({brand.name, *brand.aliases}, key=len, reverse=True)
            pattern = "|".join(
                _phrase_pattern(v, case_sensitive=brand.case_sensitive) for v in variants
            )
            flags = 0 if brand.case_sensitive else re.IGNORECASE
            self._patterns.append((brand, re.compile(pattern, flags), brand.case_sensitive))

    def find(self, text: str) -> BrandMatch | None:
        """Première enseigne citée dans le texte (la plus tôt), ou None."""
        best: BrandMatch | None = None
        lowered, kept = fold(text), fold(text, keep_case=True)
        for brand, pattern, case_sensitive in self._patterns:
            match = pattern.search(kept if case_sensitive else lowered)
            if match and (best is None or match.start() < best.position):
                best = BrandMatch(brand=brand, position=match.start())
        return best


class TermMatcher:
    """Repère des expressions (insensible à la casse et aux accents, pluriel en s/x accepté)."""

    def __init__(self, terms: Sequence[str]) -> None:
        """Compile un motif unique pour toutes les expressions."""
        variants = sorted({fold(t) for t in terms if t.strip()}, key=len, reverse=True)
        self.terms = tuple(variants)
        self._pattern = (
            re.compile(
                "|".join(_phrase_pattern(v, case_sensitive=False, plural=True) for v in variants),
                re.IGNORECASE,
            )
            if variants
            else None
        )

    def find(self, text: str) -> str | None:
        """Première expression trouvée (forme repliée), ou None."""
        if self._pattern is None:
            return None
        match = self._pattern.search(fold(text))
        return match.group(0) if match else None

    def remove(self, text: str) -> str:
        """Texte replié dont toutes les occurrences des expressions ont été retirées."""
        if self._pattern is None:
            return fold(text)
        return self._pattern.sub(" ", fold(text))


@dataclass(frozen=True)
class Classification:
    """Rubrique attribuée à une entrée, avec l'enseigne (rubrique 2) ou le terme trouvé."""

    rubric: int
    brand: Brand | None = None
    matched: str = ""


def classify(
    title: str,
    summary: str,
    brands: BrandMatcher,
    development_terms: TermMatcher,
    exclusions: TermMatcher,
) -> Classification | None:
    """Classe une entrée de flux d'après son titre et son résumé.

    1. Enseigne suivie citée (titre d'abord, puis résumé) → rubrique 2.
    2. Sinon, terme de développement en franchise présent, une fois retirées les
       expressions d'exclusion (« franchise d'assurance »...) → rubrique 1.
    3. Sinon → None (entrée écartée).
    """
    for text in (title, summary):
        found = brands.find(text)
        if found:
            return Classification(RUBRIC_BRAND_NEWS, found.brand, found.brand.name)
    cleaned = exclusions.remove(f"{title} . {summary}")
    term = development_terms.find(cleaned)
    if term:
        return Classification(RUBRIC_NEW_FRANCHISES, None, term)
    return None
