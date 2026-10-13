"""Thème de la newsletter (config/theme.yaml) : chargement, validation, contrastes WCAG."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageDraw, UnidentifiedImageError

from news_franchise.config import PROJECT_DIR, ConfigError
from news_franchise.fonts import system_font

THEME_FILE = PROJECT_DIR / "config" / "theme.yaml"
PROVISIONAL_LOGO = PROJECT_DIR / "config" / "assets" / "logo-provisoire.png"
COLOR_KEYS = ("primary", "secondary", "text", "muted", "background", "border", "opportunity")
SECTION_KEYS = ("une", *(f"rubrique_{n}" for n in range(1, 7)))
MIN_CONTRAST = 4.5
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
# Pile de polices : noms de polices séparés par des virgules (lettres, chiffres, espaces,
# tirets, guillemets) ; rien qui permette d'injecter du CSS ou une police en ligne.
_FONT_STACK = re.compile(r"""^[A-Za-z0-9 ,'"\-]+$""")
GENERIC_FAMILIES = ("serif", "sans-serif", "monospace")


class ThemeError(ConfigError):
    """Thème invalide (message en français, nommant le champ fautif)."""


@dataclass(frozen=True)
class ContrastCheck:
    """Contrôle de contraste entre deux couleurs du thème."""

    label: str
    foreground: str
    background: str
    ratio: float

    @property
    def ok(self) -> bool:
        """Vrai si le contraste atteint 4,5:1 (WCAG AA, texte courant)."""
        return self.ratio >= MIN_CONTRAST

    @property
    def ratio_label(self) -> str:
        """Ratio arrondi, à la française (« 4,48:1 »)."""
        return f"{self.ratio:.2f}".replace(".", ",") + ":1"


@dataclass(frozen=True)
class Theme:
    """Thème validé."""

    name: str
    tagline: str
    colors: dict[str, str]
    font_body: str
    font_headings: str
    logo: Path
    footer_text: str
    section_titles: dict[str, str]
    source: Path

    def contrast_checks(self) -> list[ContrastCheck]:
        """Contrastes vérifiés : texte, texte secondaire, couleur principale et badge sur
        le fond ; texte des bandeaux (couleur du fond, blanc) sur la couleur principale.

        Les gabarits n'écrivent jamais la couleur « text » sur la couleur principale : sur un
        bandeau de couleur principale, le texte prend la couleur du fond."""
        c = self.colors
        pairs = (
            ("Texte sur le fond", c["text"], c["background"]),
            ("Texte secondaire sur le fond", c["muted"], c["background"]),
            ("Titres et liens (couleur principale) sur le fond", c["primary"], c["background"]),
            ("Texte des bandeaux sur la couleur principale", c["background"], c["primary"]),
            ("Badge opportunité sur le fond", c["opportunity"], c["background"]),
        )
        return [ContrastCheck(label, fg, bg, contrast_ratio(fg, bg)) for label, fg, bg in pairs]

    def css_variables(self) -> str:
        """Déclarations CSS « --nf-… » du thème, pour un bloc :root { … }.

        Sans risque d'injection : couleurs (#RRGGBB) et polices (lettres, chiffres, espaces,
        virgules, tirets, guillemets) ont été validées au chargement."""
        lines = [f"--nf-{key}: {value};" for key, value in self.colors.items()]
        lines += [
            f"--nf-font-body: {self.font_body};",
            f"--nf-font-headings: {self.font_headings};",
        ]
        return " ".join(lines)

    def warnings(self) -> list[str]:
        """Avertissements (non bloquants) pour les contrastes inférieurs à 4,5:1."""
        return [
            f"Contraste insuffisant — {check.label} : {check.ratio_label} "
            f"({check.foreground} sur {check.background}, minimum conseillé 4,5:1)."
            for check in self.contrast_checks()
            if not check.ok
        ]


def _channel(value: int) -> float:
    """Composante sRGB linéarisée (formule WCAG 2.x)."""
    c = value / 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """Luminance relative d'une couleur #RRGGBB (WCAG)."""
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast_ratio(first: str, second: str) -> float:
    """Rapport de contraste WCAG entre deux couleurs (de 1:1 à 21:1)."""
    light, dark = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def generate_provisional_logo(path: Path = PROVISIONAL_LOGO) -> Path:
    """Crée le logo provisoire : un bandeau texte « News Franchise » (PNG 600 × 120)."""
    width, height = 600, 120
    image = Image.new("RGB", (width, height), (0x1D, 0x35, 0x57))
    draw = ImageDraw.Draw(image)
    text, font = system_font(54, "News Franchise")
    draw.text((width // 2, height // 2), text, fill=(255, 255, 255), font=font, anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    return path


def _text(data: dict[str, Any], key: str, where: str, *, max_length: int = 200) -> str:
    """Texte obligatoire, non vide, de longueur raisonnable."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ThemeError(f"{where} : « {key} » est obligatoire (texte).")
    if len(value) > max_length:
        raise ThemeError(f"{where} : « {key} » est trop long ({max_length} caractères au plus).")
    return value.strip()


def _font_stack(value: Any, key: str, where: str) -> str:
    """Pile de polices système (ex. « Arial, Helvetica, sans-serif »)."""
    if not isinstance(value, str) or not value.strip() or not _FONT_STACK.match(value):
        raise ThemeError(
            f"{where} : « fonts.{key} » doit être une liste de polices système séparées par des "
            "virgules (ex. « Arial, Helvetica, sans-serif »), sans adresse ni police en ligne."
        )
    stack = ", ".join(part.strip() for part in value.split(",") if part.strip())
    if stack.split(", ")[-1].strip("'\"").lower() not in GENERIC_FAMILIES:
        raise ThemeError(
            f"{where} : « fonts.{key} » doit se terminer par une famille générique "
            "(sans-serif, serif ou monospace), utilisée si aucune police n'est installée."
        )
    return stack


def load_theme(path: Path = THEME_FILE, project_dir: Path = PROJECT_DIR) -> Theme:
    """Lit et valide le thème. Lève ThemeError avec un message clair en cas de problème.

    Le logo provisoire (config/assets/logo-provisoire.png) est créé s'il manque ; tout
    autre logo introuvable est une erreur.
    """
    where = path.name
    if not path.is_file():
        raise ThemeError(f"Fichier de thème introuvable : {path}.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = f", ligne {mark.line + 1}" if mark is not None else ""
        raise ThemeError(
            f"{where}{line} : YAML illisible ({getattr(exc, 'problem', exc)})."
        ) from exc
    if not isinstance(data, dict):
        raise ThemeError(f"{where} : contenu invalide.")

    colors = data.get("colors")
    if not isinstance(colors, dict):
        raise ThemeError(f"{where} : le bloc « colors: » est absent ou invalide.")
    checked_colors: dict[str, str] = {}
    for key in COLOR_KEYS:
        value = colors.get(key)
        if not isinstance(value, str) or not _HEX.match(value.strip()):
            raise ThemeError(
                f"{where} : la couleur « colors.{key} » doit être au format #RRGGBB "
                f"(ex. #1D3557) ; valeur lue : {value!r}."
            )
        checked_colors[key] = value.strip().upper()

    fonts = data.get("fonts")
    if not isinstance(fonts, dict):
        raise ThemeError(f"{where} : le bloc « fonts: » est absent ou invalide.")

    logo_value = _text(data, "logo", where, max_length=300)
    logo = Path(logo_value)
    logo = logo if logo.is_absolute() else project_dir / logo
    if not logo.is_file() and logo.resolve() == PROVISIONAL_LOGO.resolve():
        generate_provisional_logo(logo)
    if not logo.is_file():
        raise ThemeError(f"{where} : logo introuvable : {logo_value} (cherché dans {logo}).")
    try:
        with Image.open(logo) as image:
            if image.format not in ("PNG", "JPEG"):
                raise ThemeError(f"{where} : le logo doit être une image PNG ou JPEG.")
    except (UnidentifiedImageError, OSError) as exc:
        raise ThemeError(f"{where} : le logo {logo_value} n'est pas une image lisible.") from exc

    titles = data.get("section_titles")
    if not isinstance(titles, dict):
        raise ThemeError(f"{where} : le bloc « section_titles: » est absent ou invalide.")
    section_titles = {
        key: _text(titles, key, f"{where}, section_titles", max_length=80) for key in SECTION_KEYS
    }

    return Theme(
        name=_text(data, "name", where, max_length=80),
        tagline=_text(data, "tagline", where),
        colors=checked_colors,
        font_body=_font_stack(fonts.get("body"), "body", where),
        font_headings=_font_stack(fonts.get("headings"), "headings", where),
        logo=logo,
        footer_text=_text(data, "footer_text", where, max_length=300),
        section_titles=section_titles,
        source=path,
    )
