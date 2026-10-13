"""Formes géométriques de la charte Carmila (p. 21-22), en SVG en ligne.

Trois formes : l'arche (rectangle surmonté d'un demi-disque), le nœud (deux demi-disques
qui se font face) et l'heptagone (côté supérieur à plat). Le motif les répète en
quinconce dans un angle, avec un bord en diagonale. Les couleurs viennent du thème
(#RRGGBB validées) : aucun texte extérieur n'entre dans ces SVG.
"""

from __future__ import annotations

import math

SHAPES = ("arch", "bowtie", "heptagon")


def _num(value: float) -> str:
    """Nombre court pour les chemins SVG (« 12 », « 12.5 »)."""
    return f"{value:.2f}".rstrip("0").rstrip(".")


def shape_path(kind: str, x: float, y: float, size: float) -> str:
    """Chemin SVG (attribut d) de la forme kind, dans le carré (x, y, size)."""
    r = size / 2
    n = _num
    if kind == "arch":
        return (
            f"M{n(x)} {n(y + size)}V{n(y + r)}"
            f"A{n(r)} {n(r)} 0 0 1 {n(x + size)} {n(y + r)}V{n(y + size)}Z"
        )
    if kind == "bowtie":
        return (
            f"M{n(x)} {n(y)}A{n(r)} {n(r)} 0 0 1 {n(x)} {n(y + size)}Z"
            f"M{n(x + size)} {n(y)}A{n(r)} {n(r)} 0 0 0 {n(x + size)} {n(y + size)}Z"
        )
    if kind == "heptagon":
        cx, cy = x + r, y + r
        start = -math.pi / 2 + math.pi / 7  # côté supérieur horizontal
        points = [
            (
                cx + r * math.cos(start + 2 * math.pi * i / 7),
                cy + r * math.sin(start + 2 * math.pi * i / 7),
            )
            for i in range(7)
        ]
        return "M" + "L".join(f"{n(px)} {n(py)}" for px, py in points) + "Z"
    raise ValueError(f"Forme inconnue : {kind!r} (attendu : {', '.join(SHAPES)}).")


def shape_svg(kind: str, color: str, size: int = 24) -> str:
    """SVG décoratif d'une forme, d'une seule couleur (masqué aux lecteurs d'écran)."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" '
        f'height="{size}" class="nl-shape" aria-hidden="true" focusable="false">'
        f'<path d="{shape_path(kind, 0, 0, size)}" fill="{color}"/></svg>'
    )


def motif_svg(
    color: str, columns: int = 7, rows: int = 7, cell: int = 30, opacity: float = 1.0
) -> str:
    """Motif de la charte pour l'angle supérieur droit d'un bandeau.

    Formes en quinconce (une colonne sur deux décalée d'une demi-cellule), de moins en moins
    nombreuses vers la gauche : le bord du motif forme une diagonale."""
    size = cell * 0.62
    paths = []
    for col in range(columns):
        # Colonnes de droite plus longues : diagonale de l'angle supérieur droit.
        visible_rows = max(1, round(rows * (col + 1) / columns))
        offset = cell / 2 if col % 2 else 0
        for row in range(visible_rows):
            kind = SHAPES[(row + col) % len(SHAPES)]
            x = col * cell + (cell - size) / 2
            y = row * cell + offset + (cell - size) / 2
            paths.append(shape_path(kind, x, y, size))
    width, height = columns * cell, rows * cell + cell / 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_num(width)} {_num(height)}" '
        f'width="{_num(width)}" height="{_num(height)}" class="nl-motif" aria-hidden="true" '
        f'focusable="false"><path d="{"".join(paths)}" fill="{color}" '
        f'fill-opacity="{_num(opacity)}"/></svg>'
    )
