"""Jeu de démonstration pour essayer la relecture sans collecte réelle.

Usage : python -m news_franchise.tools.demo [--reset]

Crée la newsletter du mois fictif 2000-01 (et seulement celui-ci) avec des articles
clairement marqués « [DÉMO] », dont les liens pointent vers https://example.com/demo/…
Ces textes sont inventés pour la démonstration : ils ne décrivent aucun fait réel. La
détection (opportunités, franchisés) est ensuite lancée sur ce mois.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import UTC, datetime

from news_franchise.bootstrap import prepare_database
from news_franchise.config import ConfigError, Settings, load_settings
from news_franchise.db import DatabaseError
from news_franchise.db.connection import get_connection
from news_franchise.detect.runner import run_detection
from news_franchise.models import Article
from news_franchise.repositories import articles, brands, newsletters

DEMO_MONTH = "2000-01"
DEMO_SOURCE = "Source de démonstration"
DEMO_PREFIX = "[DÉMO] "

# (rubrique, enseigne suivie ou None, titre, texte de l'article)
DEMO_ARTICLES: tuple[tuple[int, str | None, str, str], ...] = (
    (
        1,
        None,
        "Un nouveau réseau de boulangeries se lance en franchise",
        "Exemple fictif. Une jeune enseigne de boulangerie annonce l'ouverture de son réseau à la "
        "franchise. Elle recherche des emplacements en centre commercial pour ses cinq premières "
        "unités.",
    ),
    (
        1,
        None,
        "Le marché de la franchise progresse",
        "Exemple fictif. Le nombre de réseaux de franchise augmente encore cette année, porté par "
        "la restauration rapide et les services à la personne.",
    ),
    (
        1,
        None,
        "Portrait d'un multi-franchisé de la restauration",
        "Exemple fictif. Jean Exemple, multi-franchisé à la tête de six restaurants en Occitanie, "
        "explique sa stratégie de développement.",
    ),
    (
        1,
        None,
        "Les galeries marchandes séduisent les jeunes enseignes",
        "Exemple fictif. Plusieurs enseignes prospectent les galeries marchandes de province pour "
        "réduire leurs coûts d'implantation.",
    ),
    (
        1,
        None,
        "Franchise : les chiffres clés du semestre",
        "Exemple fictif. Les réseaux de franchise ont ouvert de nombreux points de vente ce "
        "semestre, selon une étude du secteur.",
    ),
    (
        1,
        None,
        "Une enseigne de coiffure vise 50 salons",
        "Exemple fictif. L'enseigne vise de nouvelles implantations en zone commerciale et compte "
        "doubler son réseau d'ici trois ans.",
    ),
    (
        1,
        None,
        "Les franchisés plébiscitent la formation",
        "Exemple fictif. Une enquête montre que la formation initiale reste le premier critère de "
        "choix d'un réseau.",
    ),
    (
        1,
        None,
        "<script>alert('démo')</script> Un titre piégé pour tester l'affichage",
        "Exemple fictif. Ce titre contient du code : il doit s'afficher comme du texte, sans "
        "jamais s'exécuter.",
    ),
    (
        2,
        "Pokawa",
        "Pokawa accélère son développement",
        "Exemple fictif. Pokawa recherche des emplacements en centre commercial et prévoit "
        "plusieurs ouvertures.",
    ),
    (
        2,
        "Leonidas",
        "Leonidas renouvelle ses boutiques",
        "Exemple fictif. Marie Exemple, franchisée de Leonidas à Lyon, a rénové sa boutique.",
    ),
    (
        2,
        "O'Tacos",
        "O'Tacos ouvre de nouveaux restaurants",
        "Exemple fictif. Le groupe Démonstration exploite déjà douze restaurants O'Tacos dans le "
        "Rhône.",
    ),
    (
        2,
        "Wycon",
        "Wycon lance une nouvelle gamme",
        "Exemple fictif. La marque présente une collection de maquillage pour l'hiver.",
    ),
    (
        2,
        "Easy Cash",
        "Easy Cash ferme un magasin",
        "Exemple fictif. Easy Cash ferme son magasin du centre commercial de la ville.",
    ),
)


def build_demo(settings: Settings, *, reset: bool = False) -> int:
    """Crée la newsletter de démonstration 2000-01 ; renvoie le nombre d'articles créés.

    Lève ValueError si elle existe déjà et que reset est faux.
    """
    with closing(get_connection(settings)) as conn:
        existing = newsletters.get(conn, DEMO_MONTH)
        if existing is not None:
            if not reset:
                raise ValueError(
                    "La newsletter de démonstration (janvier 2000) existe déjà. "
                    "Relancez avec --reset pour la recréer."
                )
            assert existing.id is not None
            newsletters.delete(conn, existing.id)
        newsletter = newsletters.get_or_create(conn, DEMO_MONTH)
        assert newsletter.id is not None
        created = 0
        for index, (rubric, brand_name, title, body) in enumerate(DEMO_ARTICLES, start=1):
            brand = brands.get_by_name(conn, brand_name) if brand_name else None
            article = Article(
                newsletter_id=newsletter.id,
                rubric=rubric,
                title=DEMO_PREFIX + title,
                source_name=DEMO_SOURCE,
                url=f"https://example.com/demo/{DEMO_MONTH}/article-{index}",
                brand_id=brand.id if brand else None,
                sector=brand.sector if brand else None,
                published_at=datetime(2000, 1, min(index * 2, 28), 9, 0, tzinfo=UTC),
                excerpt=body,
                body_text=body,
                collected_at=datetime(2000, 2, 1, 9, 0, tzinfo=UTC),
            )
            if articles.add(conn, article) is not None:
                created += 1
        run_detection(conn, DEMO_MONTH)
    return created


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    out: Callable[[str], None] = print,
) -> int:
    """Crée le jeu de démonstration. Codes : 0 ; 2 si déjà présent ou configuration invalide."""
    parser = argparse.ArgumentParser(
        prog="python -m news_franchise.tools.demo",
        description="Crée une newsletter de démonstration (mois fictif 2000-01).",
    )
    parser.add_argument("--reset", action="store_true", help="recréer la démonstration")
    args = parser.parse_args(argv)
    try:
        settings = settings or load_settings()
        prepare_database(settings)
        created = build_demo(settings, reset=args.reset)
    except (ValueError, ConfigError, DatabaseError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    out(f"Démonstration créée : {created} articles fictifs dans la newsletter de janvier 2000.")
    out("Ouvrez l'application, puis « Relire » → Janvier 2000. Les liens mènent à example.com.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
