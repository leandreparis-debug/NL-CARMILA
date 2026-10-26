"""Jeu de démonstration pour essayer la relecture sans collecte réelle.

Usage : python -m news_franchise.tools.demo [--reset]

Crée la newsletter du mois fictif 2000-01 (et seulement celui-ci) avec des articles
clairement marqués « [DÉMO] », dont les liens pointent vers https://example.com/demo/…,
deux ouvertures avec des photos générées (marquées « DÉMO »), quatre enseignes
rencontrées (dont une avec un résumé de rendez-vous) et trois liens de plans régionaux.
Ces textes sont inventés pour la démonstration : ils ne décrivent aucun fait réel. La
détection (opportunités, franchisés) est ensuite lancée sur ce mois.
"""

from __future__ import annotations

import argparse
import io
import random
import sys
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import UTC, datetime

from PIL import Image, ImageDraw

from news_franchise.bootstrap import prepare_database
from news_franchise.config import ConfigError, Settings, load_settings
from news_franchise.content.photos import process_photo
from news_franchise.db import DatabaseError
from news_franchise.db.connection import get_connection
from news_franchise.detect.runner import run_detection
from news_franchise.fonts import system_font
from news_franchise.models import Article, Meeting, Opening, OpeningPhoto, PlanLink
from news_franchise.repositories import (
    articles,
    brands,
    meetings,
    newsletters,
    openings,
    plan_links,
)

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


# (enseigne, lieu, jour d'ouverture, description, couleurs des photos de démonstration)
DEMO_OPENINGS: tuple[tuple[str, str, int, str, tuple[tuple[int, int, int], ...]], ...] = (
    (
        "Pokawa",
        "Centre commercial Démo-Ville, Lyon",
        12,
        "Exemple fictif : nouveau restaurant de poke bowls en galerie marchande.",
        ((32, 96, 160), (200, 120, 40)),
    ),
    (
        "Wycon",
        "Centre commercial Exemple, Nantes",
        20,
        "Exemple fictif : boutique de maquillage au rez-de-chaussée.",
        ((150, 40, 90),),
    ),
)
DEMO_MEETINGS: tuple[tuple[str, int, str], ...] = (
    (
        "Leonidas",
        8,
        "Exemple fictif : rendez-vous avec le responsable du développement.\n"
        "L'enseigne cherche 3 emplacements en galerie dans le Sud-Ouest d'ici fin d'année ; "
        "envoi de la liste des cellules disponibles prévu la semaine prochaine.",
    ),
    ("Chopstix", 14, "Exemple fictif : premier contact."),
    ("Yogurt Factory", 21, ""),
    ("Une enseigne de démonstration", 27, "Exemple fictif."),
)
DEMO_PLANS_URL = "https://example.com/demo/plans"


def demo_photo(color: tuple[int, int, int], label: str, seed: int) -> bytes:
    """Photo de démonstration (JPEG 2400 × 1800) clairement marquée « DÉMO ».

    Dégradé, formes et léger grain, pour un poids comparable à une vraie photo.
    """
    rng = random.Random(seed)
    width, height = 2400, 1800
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        shade = y / height
        draw.line(
            [(0, y), (width, y)],
            fill=tuple(int(c * (0.55 + 0.45 * shade)) for c in color),
        )
    for _ in range(40):
        x, y = rng.randrange(width), rng.randrange(height)
        size = rng.randrange(60, 360)
        tint = tuple(min(255, c + rng.randrange(0, 90)) for c in color)
        draw.ellipse([x, y, x + size, y + size], fill=tint)
    noise = Image.effect_noise((width, height), 28).convert("RGB")
    image = Image.blend(image, noise, 0.12)
    draw = ImageDraw.Draw(image)
    title, font = system_font(240, "DÉMO", "DEMO")
    draw.rectangle([0, height // 2 - 220, width, height // 2 + 220], fill=(255, 255, 255))
    draw.text((width // 2, height // 2 - 60), title, fill=(200, 20, 30), font=font, anchor="mm")
    caption, small = system_font(90, label)
    draw.text((width // 2, height // 2 + 140), caption, fill=(30, 30, 30), font=small, anchor="mm")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def _build_internal_content(conn: object, settings: Settings, newsletter_id: int) -> None:
    """Ouvertures avec photos, enseignes rencontrées et lien des plans de démonstration."""
    seed = 0
    for brand_name, location, day, description, colors in DEMO_OPENINGS:
        opening = openings.add(
            conn,  # type: ignore[arg-type]
            Opening(
                newsletter_id=newsletter_id,
                brand_name=brand_name,
                location=location,
                opening_date=datetime(2000, 1, day).date(),
                description=description,
            ),
        )
        assert opening.id is not None
        for index, color in enumerate(colors, start=1):
            seed += 1
            data = demo_photo(color, f"{brand_name} - photo {index}", seed)
            saved = process_photo(data, settings.photos_dir, DEMO_MONTH, "demo.jpg")
            openings.add_photo(
                conn,  # type: ignore[arg-type]
                OpeningPhoto(
                    opening_id=opening.id,
                    file_name=saved.file_name,
                    caption=f"[DÉMO] {brand_name}, photo {index}",
                ),
            )
    for brand_name, day, comment in DEMO_MEETINGS:
        meetings.add(
            conn,  # type: ignore[arg-type]
            Meeting(
                newsletter_id=newsletter_id,
                brand_name=brand_name,
                meeting_date=datetime(2000, 1, day).date(),
                comment=comment or None,
            ),
        )
    plan_links.replace_all(
        conn,  # type: ignore[arg-type]
        newsletter_id,
        [
            PlanLink(
                newsletter_id=newsletter_id,
                position=1,
                url=DEMO_PLANS_URL,
                label="[DÉMO] Plans Île-de-France",
            ),
            PlanLink(
                newsletter_id=newsletter_id,
                position=2,
                url=f"{DEMO_PLANS_URL}/sud-ouest",
                label="[DÉMO] Plans Sud-Ouest",
            ),
            PlanLink(
                newsletter_id=newsletter_id,
                position=3,
                url=f"{DEMO_PLANS_URL}/sud-est",
                label="[DÉMO] Plans Sud-Est",
            ),
        ],
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
            newsletters.delete(conn, existing.id, settings.photos_dir)
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
        _build_internal_content(conn, settings, newsletter.id)
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
