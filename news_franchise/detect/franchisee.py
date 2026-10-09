"""Franchisés identifiés : phrases déclencheuses puis extraction des champs de la fiche."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from news_franchise.collect.matching import BrandMatcher
from news_franchise.collect.text import fold
from news_franchise.detect.places import PlaceMatcher
from news_franchise.detect.rules import FranchiseeRules
from news_franchise.detect.text import keep_length_apostrophes, strip_accents_keep_length
from news_franchise.models import Brand

_UPPER = "A-ZÀ-ÖØ-Þ"
_LOWER = "a-zß-öø-ÿ"
# Mot de nom de personne : « Jean », « Jean-Pierre », « Dupont », ou nom en capitales « DUPONT ».
_NAME_WORD = rf"[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)?"
_CAPS_WORD = rf"[{_UPPER}]{{2,}}(?:-[{_UPPER}]{{2,}})?"
_PARTICLE = r"(?:de |du |des |d'|le |la |van |von |ben |el )"
_PERSON = re.compile(
    rf"(?<![\w'])(?P<name>{_NAME_WORD}(?:\s+{_PARTICLE}?(?:{_NAME_WORD}|{_CAPS_WORD})){{1,3}})(?![\w])"
)
# Mot d'un nom de société : commence par une majuscule ou un chiffre.
_COMPANY_WORD = rf"[{_UPPER}0-9][\w&'.-]*"
_COMPANY_NAME = rf"{_COMPANY_WORD}(?:\s+(?:&\s+)?{_COMPANY_WORD}){{0,3}}"
_FRANCHISEE_OF = re.compile(
    r"(?i:franchisée?s?\s+(?:de|du|des|d')\s*(?:l'enseigne\s+|la\s+marque\s+)?)"
    rf"(?P<brand>{_COMPANY_WORD}(?:\s+{_COMPANY_WORD}){{0,2}})"
)

CONFIDENCE_HIGH = "haute"
CONFIDENCE_MEDIUM = "moyenne"
CONFIDENCE_LOW = "basse"


def name_key(name: str) -> str:
    """Forme normalisée d'un nom pour le dédoublonnage (casse, accents, ponctuation)."""
    return " ".join(re.sub(r"[^\w]+", " ", fold(name)).split())


@dataclass
class FranchiseeCandidate:
    """Franchisé détecté dans un article (suggestion à valider)."""

    name: str
    evidence: str
    trigger_terms: list[str]
    brands: list[str] = field(default_factory=list)
    location: str | None = None
    store_count: int | None = None
    name_in_evidence: bool = True  # le nom figure dans la phrase justificative

    @property
    def confidence(self) -> str:
        """« haute » : nom + enseigne + nombre ; « moyenne » : nom + enseigne ; « basse »."""
        if self.brands and self.store_count is not None:
            return CONFIDENCE_HIGH
        if self.brands:
            return CONFIDENCE_MEDIUM
        return CONFIDENCE_LOW

    @property
    def key(self) -> str:
        """Clé de dédoublonnage."""
        return name_key(self.name)

    def complete_with(self, other: FranchiseeCandidate) -> None:
        """Complète les champs vides avec une autre occurrence du même franchisé
        (la source et la phrase justificative de la première sont conservées)."""
        if not self.brands:
            self.brands = list(other.brands)
        if self.location is None:
            self.location = other.location
        if self.store_count is None:
            self.store_count = other.store_count


@dataclass(frozen=True)
class UnnamedTrigger:
    """Phrase déclencheuse dans laquelle aucun nom n'a été trouvé (pas de fiche)."""

    sentence: str
    trigger_terms: tuple[str, ...]


@dataclass(frozen=True)
class _NameHit:
    """Nom trouvé et sa position dans la phrase."""

    name: str
    position: int


class FranchiseeExtractor:
    """Repère les phrases déclencheuses et extrait nom, enseigne(s), lieu et nombre."""

    def __init__(
        self, rules: FranchiseeRules, places: PlaceMatcher, brand_matcher: BrandMatcher
    ) -> None:
        """Prépare les motifs à partir des règles."""
        self.rules = rules
        self.places = places
        self.brand_matcher = brand_matcher
        markers = "|".join(
            re.escape(keep_length_apostrophes(m)).replace(r"\ ", r"\s+")
            for m in sorted(rules.company_markers, key=len, reverse=True)
        )
        self._company_marker = re.compile(
            rf"(?<![\w])(?P<marker>(?i:{markers}))\s+(?P<name>{_COMPANY_NAME})"
        )
        suffixes = "|".join(
            re.escape(s) for s in sorted(rules.company_suffixes, key=len, reverse=True)
        )
        self._company_suffix = re.compile(
            rf"(?<![\w'])(?P<name>{_COMPANY_NAME})\s+(?P<suffix>{suffixes})(?![\w])"
        )
        number_words = "|".join(
            re.escape(strip_accents_keep_length(w))
            for w in sorted(rules.number_words, key=len, reverse=True)
        )
        units = "|".join(
            re.escape(strip_accents_keep_length(u)).replace(r"\ ", r"\s+")
            for u in sorted(rules.store_units, key=len, reverse=True)
        )
        self._count = re.compile(
            rf"(?<![\w-])(?P<n>\d{{1,4}}|{number_words})\s+(?:{units})(?![\w])", re.IGNORECASE
        )
        self._stopwords = {w.casefold() for w in rules.name_stopwords}

    # ------------------------------------------------------------------ déclencheurs

    def triggers(self, sentence: str) -> list[re.Match[str]]:
        """Correspondances des motifs déclencheurs dans la phrase (accents respectés)."""
        text = keep_length_apostrophes(sentence)
        matches = [m for pattern in self.rules.compiled_triggers for m in pattern.finditer(text)]
        return sorted(matches, key=lambda m: m.start())

    # ------------------------------------------------------------------ champs

    def _is_stopword(self, word: str) -> bool:
        """Mot à majuscule qui n'est jamais un nom (début de phrase, titre, mois...)."""
        base = word.split("'")[0]
        return word.casefold() in self._stopwords or base.casefold() in self._stopwords

    def _clean_person(self, raw: str) -> str | None:
        """Retire les mots vides en tête et en fin ; refuse enseignes et lieux."""
        words = raw.split()
        while words and self._is_stopword(words[0]):
            words.pop(0)
        while words and self._is_stopword(words[-1]):
            words.pop()
        capitalized = [w for w in words if w[:1].isupper()]
        if len(capitalized) < 2 or any(self._is_stopword(w) for w in capitalized):
            return None
        name = " ".join(words)
        if self.brand_matcher.find(name) or self.places.is_place_name(name):
            return None
        return name

    def _clean_company(self, raw: str) -> str | None:
        """Nom de société sans mots vides de fin ; refuse un nom d'enseigne ou de lieu."""
        words = raw.split()
        while words and self._is_stopword(words[-1]):
            words.pop()
        if not words:
            return None
        name = " ".join(words)
        if self.brand_matcher.find(name) or self.places.is_place_name(name):
            return None
        return name

    def names(self, sentence: str) -> list[_NameHit]:
        """Noms de personne ou de société trouvés dans la phrase, avec leur position."""
        text = keep_length_apostrophes(sentence)
        hits: list[_NameHit] = []
        for match in self._company_marker.finditer(text):
            name = self._clean_company(match.group("name"))
            if name:
                marker = fold(match.group("marker"))
                prefix = "Groupe " if marker.endswith("groupe") else ""
                prefix = "Holding " if marker.endswith("holding") else prefix
                hits.append(_NameHit(prefix + name, match.start()))
        for match in self._company_suffix.finditer(text):
            name = self._clean_company(match.group("name"))
            if name:
                hits.append(_NameHit(f"{name} {match.group('suffix')}", match.start()))
        covered = [(h.position, h.position + len(h.name) + 12) for h in hits]
        # Le nom propre qui suit « franchisé de » est l'enseigne, pas le franchisé.
        covered += [m.span("brand") for m in _FRANCHISEE_OF.finditer(text)]
        for match in _PERSON.finditer(text):
            if any(start <= match.start() < end for start, end in covered):
                continue
            name = self._clean_person(match.group("name"))
            if name:
                hits.append(_NameHit(name, match.start()))
        return hits

    def store_count(self, sentence: str) -> int | None:
        """Nombre de points de vente (« cinq restaurants », « 12 magasins »), ou None."""
        match = self._count.search(strip_accents_keep_length(sentence))
        if not match:
            return None
        raw = match.group("n").lower()
        value = int(raw) if raw.isdigit() else self.rules.number_words.get(raw)
        return value if value and 0 < value <= 5000 else None

    def brands(self, sentences: Sequence[str], article_brand: Brand | None) -> list[str]:
        """Enseignes suivies citées dans la phrase déclencheuse (à défaut, dans ses
        voisines), plus l'enseigne de l'article ; sinon le nom propre qui suit
        « franchisé de »."""
        names: list[str] = []
        for sentence in sentences:
            names = [b.name for b in self.brand_matcher.find_all(sentence)]
            if names:
                break
        if article_brand is not None:
            names.append(article_brand.name)
        if not names:
            for sentence in sentences:
                match = _FRANCHISEE_OF.search(keep_length_apostrophes(sentence))
                if match:
                    candidate = self._clean_company(match.group("brand"))
                    if candidate:
                        names.append(candidate)
                        break
        return list(dict.fromkeys(names))

    # ------------------------------------------------------------------ article

    def extract(
        self, sentences: Sequence[str], article_brand: Brand | None = None
    ) -> tuple[list[FranchiseeCandidate], list[UnnamedTrigger]]:
        """Analyse les phrases d'un article : fiches candidates et déclencheurs sans nom.

        Les champs sont cherchés dans la phrase déclencheuse, puis dans la phrase
        précédente et la suivante.
        """
        candidates: dict[str, FranchiseeCandidate] = {}
        unnamed: list[UnnamedTrigger] = []
        for index, sentence in enumerate(sentences):
            matches = self.triggers(sentence)
            if not matches:
                continue
            terms = list(dict.fromkeys(m.group(0) for m in matches))
            window = [sentence]
            if index > 0:
                window.append(sentences[index - 1])
            if index + 1 < len(sentences):
                window.append(sentences[index + 1])

            trigger_position = matches[0].start()
            in_sentence = self.names(sentence)
            if in_sentence:
                name = min(in_sentence, key=lambda h: abs(h.position - trigger_position)).name
            else:
                neighbours = [hit for s in window[1:] for hit in self.names(s)]
                name = neighbours[0].name if neighbours else None
            if name is None:
                unnamed.append(UnnamedTrigger(sentence, tuple(terms)))
                continue

            candidate = FranchiseeCandidate(
                name=name,
                evidence=sentence,
                trigger_terms=terms,
                brands=self.brands(window, article_brand),
                location=next((p for s in window if (p := self.places.find(s))), None),
                store_count=next(
                    (c for s in window if (c := self.store_count(s)) is not None), None
                ),
                name_in_evidence=bool(in_sentence),
            )
            existing = candidates.get(candidate.key)
            if existing is None:
                candidates[candidate.key] = candidate
                continue
            if not existing.name_in_evidence and candidate.name_in_evidence:
                # Même article : on préfère la phrase qui cite le nom comme justification.
                existing.evidence = candidate.evidence
                existing.trigger_terms = list(
                    dict.fromkeys(existing.trigger_terms + candidate.trigger_terms)
                )
                existing.name_in_evidence = True
            existing.complete_with(candidate)
        return list(candidates.values()), unnamed
