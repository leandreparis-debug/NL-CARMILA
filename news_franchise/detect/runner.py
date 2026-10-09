"""Détection d'un mois : analyse des articles en base, puis enregistrement prudent."""

from __future__ import annotations

import logging
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from news_franchise.collect.matching import BrandMatcher
from news_franchise.db.connection import transaction
from news_franchise.detect.franchisee import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    FranchiseeCandidate,
    FranchiseeExtractor,
    UnnamedTrigger,
    name_key,
)
from news_franchise.detect.opportunity import OpportunityDetector, OpportunityMatch
from news_franchise.detect.places import PlaceMatcher
from news_franchise.detect.rules import (
    DETECTION_RULES_FILE,
    PLACES_FILE,
    DetectionRules,
    Places,
    load_detection_rules,
    load_places,
)
from news_franchise.detect.text import article_sentences
from news_franchise.models import Article, Franchisee, validate_month
from news_franchise.repositories import articles, brands, franchisees, newsletters

logger = logging.getLogger(__name__)

CONFIDENCE_ORDER = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)


@dataclass(frozen=True)
class OpportunityFinding:
    """Article marqué « opportunité » par les règles, avec sa preuve."""

    article: Article
    match: OpportunityMatch


@dataclass
class CandidateFinding:
    """Franchisé candidat et article d'origine (sa source)."""

    candidate: FranchiseeCandidate
    article: Article


@dataclass(frozen=True)
class UnnamedFinding:
    """Phrase déclencheuse sans nom (aucune fiche créée)."""

    trigger: UnnamedTrigger
    article: Article


@dataclass
class DetectionReport:
    """Bilan d'une détection sur un mois."""

    month: str
    articles_analysed: int = 0
    opportunities: list[OpportunityFinding] = field(default_factory=list)
    candidates: list[CandidateFinding] = field(default_factory=list)
    unnamed: list[UnnamedFinding] = field(default_factory=list)
    protected_opportunities: int = 0  # repères modifiés à la main, laissés tels quels
    franchisees_created: int = 0
    franchisees_updated: int = 0
    protected_franchisees: int = 0  # fiches validées, modifiées, écartées ou manuelles
    suggestions_removed: int = 0
    dry_run: bool = False

    @property
    def by_confidence(self) -> dict[str, int]:
        """Nombre de franchisés candidats par niveau de confiance."""
        counts = Counter(f.candidate.confidence for f in self.candidates)
        return {level: counts.get(level, 0) for level in CONFIDENCE_ORDER}

    def summary(self) -> dict[str, Any]:
        """Bilan chiffré (enregistré avec les statistiques de la collecte)."""
        return {
            "articles_analysed": self.articles_analysed,
            "opportunities": len(self.opportunities),
            "protected_opportunities": self.protected_opportunities,
            "franchisees": self.by_confidence,
            "triggers_without_name": len(self.unnamed),
            "franchisees_created": self.franchisees_created,
            "franchisees_updated": self.franchisees_updated,
            "protected_franchisees": self.protected_franchisees,
            "suggestions_removed": self.suggestions_removed,
        }


@dataclass(frozen=True)
class Detector:
    """Règles prêtes à l'emploi (détecteurs compilés)."""

    rules: DetectionRules
    opportunity: OpportunityDetector
    franchisee: FranchiseeExtractor


def build_detector(
    conn: sqlite3.Connection,
    rules: DetectionRules | None = None,
    places: Places | None = None,
    *,
    rules_path: Path = DETECTION_RULES_FILE,
    places_path: Path = PLACES_FILE,
) -> Detector:
    """Charge et compile les règles (lève DetectionRulesError si un fichier est invalide)."""
    rules = rules or load_detection_rules(rules_path)
    places = places or load_places(places_path)
    brand_matcher = BrandMatcher(brands.list_all(conn, tracked_only=True))
    return Detector(
        rules=rules,
        opportunity=OpportunityDetector(rules.opportunity),
        franchisee=FranchiseeExtractor(rules.franchisee, PlaceMatcher(places), brand_matcher),
    )


def analyse_month(conn: sqlite3.Connection, month: str, detector: Detector) -> DetectionReport:
    """Applique les règles aux articles du mois, sans rien écrire en base.

    Les franchisés sont dédoublonnés sur le mois (nom normalisé) : la première occurrence
    garde sa source et sa phrase, les suivantes complètent ses champs vides.
    """
    report = DetectionReport(month=validate_month(month), dry_run=True)
    newsletter = newsletters.get(conn, report.month)
    if newsletter is None or newsletter.id is None:
        return report
    brand_by_id = {b.id: b for b in brands.list_all(conn)}
    merged: dict[str, CandidateFinding] = {}
    for article in articles.list_for_newsletter(conn, newsletter.id):
        report.articles_analysed += 1
        sentences = article_sentences(article.title, article.excerpt, article.body_text)
        match = detector.opportunity.detect(sentences)
        if match:
            report.opportunities.append(OpportunityFinding(article, match))
        found, unnamed = detector.franchisee.extract(sentences, brand_by_id.get(article.brand_id))
        report.unnamed += [UnnamedFinding(trigger, article) for trigger in unnamed]
        for candidate in found:
            if candidate.key in merged:
                merged[candidate.key].candidate.complete_with(candidate)
            else:
                merged[candidate.key] = CandidateFinding(candidate, article)
    report.candidates = list(merged.values())
    return report


def _save(conn: sqlite3.Connection, report: DetectionReport, newsletter_id: int) -> None:
    """Enregistre les détections sans jamais toucher au travail de l'utilisateur."""
    marked = {f.article.id: f.match for f in report.opportunities}
    for article in articles.list_for_newsletter(conn, newsletter_id):
        assert article.id is not None
        match = marked.get(article.id)
        if article.opportunity_source == "manual":
            report.protected_opportunities += 1
            continue
        articles.apply_auto_opportunity(
            conn,
            article.id,
            match is not None,
            match.sentence if match else None,
            match.terms if match else (),
        )

    existing = {
        name_key(f.name): f
        for f in franchisees.list_for_newsletter(conn, newsletter_id, include_dismissed=True)
    }
    kept_ids: list[int] = []
    for finding in report.candidates:
        candidate, article = finding.candidate, finding.article
        fiche = Franchisee(
            newsletter_id=newsletter_id,
            name=candidate.name,
            brands=", ".join(candidate.brands),
            location=candidate.location,
            store_count=candidate.store_count,
            source_name=article.source_name,
            source_url=article.url,  # toujours l'URL de l'article d'origine
            article_id=article.id,
            confidence=candidate.confidence,
            evidence=candidate.evidence,
            trigger_terms=list(candidate.trigger_terms),
        )
        current = existing.get(candidate.key)
        if current is None:
            created = franchisees.add(conn, fiche)
            assert created.id is not None
            kept_ids.append(created.id)
            report.franchisees_created += 1
            continue
        assert current.id is not None
        kept_ids.append(current.id)
        protected = (
            current.validated or current.edited or current.dismissed or current.confidence is None
        )
        if protected:
            report.protected_franchisees += 1
            continue
        fiche.id = current.id
        if franchisees.apply_auto_update(conn, fiche):
            report.franchisees_updated += 1
    report.suggestions_removed = franchisees.delete_stale_suggestions(conn, newsletter_id, kept_ids)


def run_detection(
    conn: sqlite3.Connection,
    month: str,
    *,
    dry_run: bool = False,
    rules_path: Path = DETECTION_RULES_FILE,
    places_path: Path = PLACES_FILE,
) -> DetectionReport:
    """Détecte opportunités et franchisés candidats pour le mois AAAA-MM.

    Les règles sont chargées avant toute écriture : si elles sont invalides,
    DetectionRulesError est levée et la base n'est pas modifiée. L'enregistrement se
    fait dans une seule transaction. Jamais modifiés : repère « opportunité » posé ou
    retiré à la main, franchisé validé, modifié ou écarté, fiche saisie à la main. Les
    suggestions jamais touchées que les règles ne trouvent plus sont retirées.

    dry_run=True : analyse seulement (outil de mesure de fiabilité).
    """
    month = validate_month(month)
    detector = build_detector(conn, rules_path=rules_path, places_path=places_path)
    report = analyse_month(conn, month, detector)
    report.dry_run = dry_run
    if dry_run:
        return report
    newsletter = newsletters.get(conn, month)
    if newsletter is None or newsletter.id is None:
        return report
    with transaction(conn):
        _save(conn, report, newsletter.id)
    logger.info("Détection %s : %s", month, report.summary())
    return report
