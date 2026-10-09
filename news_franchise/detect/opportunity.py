"""Repère « opportunité » : l'enseigne cherche des emplacements."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from news_franchise.collect.matching import TermMatcher
from news_franchise.detect.rules import OpportunityRules


@dataclass(frozen=True)
class OpportunityMatch:
    """Phrase qui justifie le repère et termes trouvés."""

    sentence: str
    terms: tuple[str, ...]
    kind: str  # "strong" (expression forte) ou "search+place"


class OpportunityDetector:
    """Applique les règles du repère « opportunité » phrase par phrase."""

    def __init__(self, rules: OpportunityRules) -> None:
        """Prépare les listes de termes."""
        self.search = TermMatcher(rules.search_terms)
        self.place = TermMatcher(rules.place_terms)
        self.strong = TermMatcher(rules.strong_terms)
        self.exclusions = TermMatcher(rules.exclusions)

    def check_sentence(self, sentence: str) -> OpportunityMatch | None:
        """Résultat pour une phrase : expression forte seule, ou terme de recherche ET
        terme de lieu dans la même phrase ; une phrase d'exclusion est ignorée."""
        if self.exclusions.find_all(sentence):
            return None
        strong = self.strong.find_all(sentence)
        if strong:
            return OpportunityMatch(sentence, tuple(strong), "strong")
        search = self.search.find_all(sentence)
        if not search:
            return None
        place = self.place.find_all(sentence)
        if not place:
            return None
        return OpportunityMatch(sentence, tuple(search + place), "search+place")

    def detect(self, sentences: Sequence[str]) -> OpportunityMatch | None:
        """Première phrase (titre d'abord) qui justifie le repère, ou None."""
        for sentence in sentences:
            match = self.check_sentence(sentence)
            if match:
                return match
        return None

    def terms_in(self, sentence: str) -> list[str]:
        """Tous les termes des trois listes présents dans la phrase (pour repérer les oublis)."""
        found = self.strong.find_all(sentence) + self.search.find_all(sentence)
        return list(dict.fromkeys(found + self.place.find_all(sentence)))
