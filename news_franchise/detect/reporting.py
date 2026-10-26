"""Mise en forme des résultats de détection : bilan texte et rapport de fiabilité."""

from __future__ import annotations

from datetime import datetime

from news_franchise.detect.opportunity import OpportunityDetector
from news_franchise.detect.runner import DetectionReport
from news_franchise.detect.text import article_sentences
from news_franchise.models import Article

CONFIDENCE_LABELS = {"haute": "haute", "moyenne": "moyenne", "basse": "basse"}


def format_summary(report: DetectionReport, examples: int = 5) -> list[str]:
    """Bilan lisible en français (lignes de texte) avec quelques exemples justifiés."""
    by_confidence = report.by_confidence
    lines = [
        f"Détection {report.month}{' (simulation)' if report.dry_run else ''} : "
        f"{report.articles_analysed} article(s) analysé(s)",
        f"  Opportunités détectées             : {len(report.opportunities)}",
        f"  Repères modifiés à la main (gardés): {report.protected_opportunities}",
        "  Franchisés candidats               : "
        f"{sum(by_confidence.values())} (confiance haute {by_confidence['haute']}, "
        f"moyenne {by_confidence['moyenne']}, basse {by_confidence['basse']})",
        f"  Phrases déclencheuses sans nom     : {len(report.unnamed)}",
    ]
    if not report.dry_run:
        lines.append(
            f"  Fiches créées / mises à jour / protégées / retirées : {report.franchisees_created}"
            f" / {report.franchisees_updated} / {report.protected_franchisees}"
            f" / {report.suggestions_removed}"
        )
    shown = 0
    if examples > 0 and (report.opportunities or report.candidates):
        lines += ["", "Exemples :"]
    for finding in report.opportunities:
        if shown >= examples:
            break
        lines += [
            f"  • Opportunité : {finding.article.title}",
            f"    Phrase : « {finding.match.sentence} »",
            f"    Termes : {', '.join(finding.match.terms)}",
            f"    Lien : {finding.article.url}",
        ]
        shown += 1
    for finding in report.candidates:
        if shown >= examples:
            break
        c = finding.candidate
        lines += [
            f"  • Franchisé : {c.name} - enseigne(s) : {', '.join(c.brands) or '-'} - "
            f"lieu : {c.location or '-'} - points de vente : {c.store_count or '-'} - "
            f"confiance {c.confidence}",
            f"    Phrase : « {c.evidence} »",
            f"    Source : {finding.article.source_name} - {finding.article.url}",
        ]
        shown += 1
    return lines


def _md(text: str) -> str:
    """Texte sûr pour une ligne Markdown."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _article_line(article: Article) -> str:
    """Titre, source et lien d'un article."""
    return f"[{_md(article.title)}]({article.url}) - {_md(article.source_name)}"


def render_evaluation(
    report: DetectionReport, detector: OpportunityDetector, articles: list[Article], now: datetime
) -> str:
    """Rapport Markdown de fiabilité : chaque détection avec sa preuve et une case
    « juste / faux » à cocher, puis les articles non marqués contenant un terme (oublis)."""
    marked = {f.article.id for f in report.opportunities}
    near_misses: list[tuple[Article, list[tuple[str, list[str]]]]] = []
    for article in articles:
        if article.id in marked:
            continue
        hits = [
            (sentence, terms)
            for sentence in article_sentences(article.title, article.excerpt, article.body_text)
            if (terms := detector.terms_in(sentence))
        ]
        if hits:
            near_misses.append((article, hits))

    by_confidence = report.by_confidence
    lines = [
        f"# Fiabilité de la détection - {report.month}",
        "",
        f"Généré le {now.astimezone():%d/%m/%Y à %H:%M} à partir des articles en base "
        "(simulation : la base n'est pas modifiée).",
        "",
        "## Comment remplir ce rapport",
        "",
        "Pour chaque détection, ouvrez le lien si besoin, puis cochez **juste** ou **faux** "
        "(remplacez `[ ]` par `[x]`). Pour les articles non marqués, cochez **oubli** si "
        "l'article aurait dû être marqué.",
        "",
        "- Précision du repère = nombre de « juste » ÷ nombre d'opportunités détectées.",
        "- Oublis = nombre d'« oubli » cochés dans la dernière partie.",
        "- Repère à garder si la précision est élevée (par exemple ≥ 80 %) et les oublis rares.",
        "",
        "## Synthèse",
        "",
        "| Mesure | Nombre |",
        "|---|---|",
        f"| Articles analysés | {report.articles_analysed} |",
        f"| Opportunités détectées | {len(report.opportunities)} |",
        f"| Articles non marqués contenant un terme | {len(near_misses)} |",
        f"| Franchisés candidats (haute / moyenne / basse) | {by_confidence['haute']} / "
        f"{by_confidence['moyenne']} / {by_confidence['basse']} |",
        f"| Phrases déclencheuses sans nom | {len(report.unnamed)} |",
        "",
        f"## 1. Opportunités détectées ({len(report.opportunities)})",
    ]
    if not report.opportunities:
        lines += ["", "_Aucune._"]
    for index, finding in enumerate(report.opportunities, start=1):
        kind = (
            "expression forte"
            if finding.match.kind == "strong"
            else "terme de recherche + terme de lieu"
        )
        lines += [
            "",
            f"### O{index}. {_md(finding.article.title)}",
            "",
            f"- Article : {_article_line(finding.article)}",
            f"- Phrase : « {_md(finding.match.sentence)} »",
            f"- Termes : {', '.join(finding.match.terms)} ({kind})",
            "- Verdict proposé : **opportunité**",
            "- [ ] juste  - [ ] faux",
        ]

    lines += ["", f"## 2. Franchisés candidats ({len(report.candidates)})"]
    if not report.candidates:
        lines += ["", "_Aucun._"]
    for index, finding in enumerate(report.candidates, start=1):
        c = finding.candidate
        lines += [
            "",
            f"### F{index}. {_md(c.name)} - confiance {c.confidence}",
            "",
            f"- Enseigne(s) : {_md(', '.join(c.brands)) or '-'} ; "
            f"lieu : {_md(c.location or '-')} ; "
            f"points de vente : {c.store_count if c.store_count is not None else '-'}",
            f"- Article : {_article_line(finding.article)}",
            f"- Phrase : « {_md(c.evidence)} »",
            f"- Termes déclencheurs : {', '.join(c.trigger_terms)}",
            "- Verdict proposé : **franchisé à approcher**",
            "- [ ] juste  - [ ] faux (pas un franchisé, ou nom/enseigne/lieu erroné)",
        ]

    lines += ["", f"## 3. Phrases déclencheuses sans nom ({len(report.unnamed)})"]
    if not report.unnamed:
        lines += ["", "_Aucune._"]
    for finding in report.unnamed:
        lines += [
            "",
            f"- {_article_line(finding.article)}",
            f"  - Phrase : « {_md(finding.trigger.sentence)} »",
            f"  - Termes : {', '.join(finding.trigger.trigger_terms)}",
            "  - [ ] un franchisé est cité ailleurs dans l'article (oubli)",
        ]

    lines += [
        "",
        f"## 4. Articles non marqués contenant un terme d'opportunité ({len(near_misses)})",
        "",
        "Ces articles contiennent au moins un terme des listes, sans remplir la règle "
        "(par exemple un terme de recherche sans terme de lieu dans la même phrase).",
    ]
    if not near_misses:
        lines += ["", "_Aucun._"]
    for article, hits in near_misses:
        lines += ["", f"- {_article_line(article)}"]
        for sentence, terms in hits[:3]:
            lines.append(f"  - « {_md(sentence)} » - termes : {', '.join(terms)}")
        lines.append("  - [ ] oubli (aurait dû être marqué)")
    return "\n".join(lines) + "\n"
