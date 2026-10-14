"""Habillage du back-office aux couleurs de la charte Carmila : navigation, icônes, motif.

Les couleurs viennent du thème (config/theme.yaml) quand il est valide ; sinon la feuille
de style garde ses valeurs par défaut (celles de la charte) et l'application reste
utilisable.
"""

from __future__ import annotations

from dataclasses import dataclass

from flask import current_app, has_request_context, request, url_for
from markupsafe import Markup

from news_franchise.newsletter.shapes import motif_svg, shape_svg
from news_franchise.newsletter.theme import THEME_FILE, ThemeError, contrast_ratio, load_theme

# Couleurs de la charte (p. 11), utilisées si le thème est illisible.
CHARTE_ACCENTS = ("#EF4050", "#60C3AD", "#FEC46F", "#FFCC32", "#5192BB", "#FFF1E2")


@dataclass(frozen=True)
class Feature:
    """Fonction de l'application : libellé, route, description, forme de la charte."""

    key: str
    label: str
    endpoint: str
    description: str
    shape: str  # arch, bowtie ou heptagon


FEATURES: tuple[Feature, ...] = (
    Feature(
        "collecte",
        "Collecter la veille",
        "collect.index",
        "Lire les sources d'actualité du mois et repérer franchisés et opportunités.",
        "bowtie",
    ),
    Feature(
        "relecture",
        "Relire",
        "review.index",
        "Choisir les articles, les ordonner, valider les franchisés.",
        "arch",
    ),
    Feature(
        "contenu",
        "Contenu interne",
        "content.start",
        "Ajouter les ouvertures et leurs photos, les enseignes rencontrées, les plans.",
        "heptagon",
    ),
    Feature(
        "export",
        "Exporter",
        "newsletter.exports",
        "Préparer l'e-mail Gmail du mois, prêt à devenir un brouillon.",
        "bowtie",
    ),
    Feature(
        "theme",
        "Thème",
        "newsletter.theme",
        "Vérifier la charte appliquée : couleurs, logos, polices et contrastes.",
        "arch",
    ),
)

# Entrées du menu : (clé, libellé, route).
NAV: tuple[tuple[str, str, str], ...] = (
    ("accueil", "Accueil", "index"),
    ("relecture", "Newsletters", "review.index"),
    ("collecte", "Collecter la veille", "collect.index"),
    ("contenu", "Contenu interne", "content.start"),
    ("export", "Exporter", "newsletter.exports"),
    ("theme", "Thème", "newsletter.theme"),
)
_NAV_SHAPES = {"accueil": "heptagon", **{f.key: f.shape for f in FEATURES}}


def active_section(endpoint: str | None) -> str:
    """Entrée du menu à mettre en évidence pour la page affichée."""
    if not endpoint or endpoint == "index":
        return "accueil"
    if endpoint == "content.start":
        return "contenu"
    if endpoint.startswith("collect."):
        return "collecte"
    if endpoint in ("newsletter.theme", "newsletter.logo"):
        return "theme"
    if endpoint == "newsletter.exports" or endpoint.startswith("newsletter.export"):
        return "export"
    # Écran du mois (relecture et contenu interne), aperçu.
    return "relecture"


SIDEBAR_DEFAULT = "#004D46"


def _visible_on(colors: tuple[str, ...], background: str) -> tuple[str, ...]:
    """Couleurs qui se distinguent du fond (formes décoratives : contraste d'au moins 2:1)."""
    visible = tuple(color for color in colors if contrast_ratio(color, background) >= 2)
    return visible or ("#FFFFFF",)


def _accents() -> tuple[tuple[str, ...], tuple[str, ...], Markup]:
    """Couleurs d'accent (cartes sur fond blanc, menu sur fond vert) et variables CSS du
    thème ; valeurs de la charte si le thème est invalide."""
    try:
        theme = load_theme(current_app.config.get("NF_THEME_FILE", THEME_FILE))
    except ThemeError:
        return CHARTE_ACCENTS, _visible_on(CHARTE_ACCENTS, SIDEBAR_DEFAULT), Markup("")
    colors = tuple(dict.fromkeys(theme.section_colors.values())) or CHARTE_ACCENTS
    nav_colors = _visible_on(colors, theme.colors["secondary"])
    # Valeurs validées au chargement du thème (#RRGGBB, polices système).
    return colors, nav_colors, Markup(theme.css_variables())


def ui_context() -> dict[str, object]:
    """Variables du gabarit de base : menu (avec icônes), motif, variables du thème.

    Vide hors requête HTTP (gabarits de l'e-mail rendus pendant un export)."""
    if not has_request_context():
        return {}
    accents, nav_accents, theme_css = _accents()
    active = active_section(request.endpoint)
    nav = [
        {
            "label": label,
            "url": url_for(endpoint),
            "active": key == active,
            "icon": Markup(
                shape_svg(_NAV_SHAPES[key], nav_accents[index % len(nav_accents)], 16)
            ),
        }
        for index, (key, label, endpoint) in enumerate(NAV)
    ]
    features = [
        {
            "feature": feature,
            "url": url_for(feature.endpoint),
            "icon": Markup(shape_svg(feature.shape, accents[index % len(accents)], 40)),
        }
        for index, feature in enumerate(FEATURES)
    ]
    return {
        "nav_items": nav,
        "feature_cards": features,
        "ui_theme_css": theme_css,
        "ui_motif": Markup(motif_svg("#FFFFFF", columns=6, rows=6, cell=26, opacity=0.14)),
        "ui_motif_hero": Markup(motif_svg("#FFFFFF", columns=7, rows=7, cell=30, opacity=0.9)),
    }
