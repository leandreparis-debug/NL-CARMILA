# Thème de la newsletter : la charte Carmila

Toute la charte graphique de la newsletter tient dans un seul fichier :
**`config/theme.yaml`**. Les gabarits (`news_franchise/templates/newsletter/_*.html`) et la
feuille de style (`news_franchise/static/newsletter.css`) n'utilisent que ces valeurs : il
n'y a rien d'autre à modifier pour changer l'apparence.

Le thème applique la charte **« Les fondamentaux de la marque Carmila » (avril 2023)**.

## Ce qui vient de la charte

| Élément | Charte | Dans la newsletter |
| --- | --- | --- |
| Couleurs (p. 11) | rouge `#EF4050` et jaune `#FFCC32` (identitaires) ; turquoise `#60C3AD`, orange `#FEC46F` (principales) ; crème `#FFF1E2`, vert foncé `#004D46`, bleu `#5192BB`, gris `#58595B` (secondaires) | bandeau rouge ; titres et liens en vert foncé ; texte en gris ; encadrés crème ; badge opportunité jaune ; une couleur d'accent par rubrique |
| Typographie (p. 13-15) | Josefin Sans (principale), Oswald (encadrés, chiffres), **Century Gothic** comme police système de substitution | texte et titres : Century Gothic ; chiffres et petits libellés : Bahnschrift Condensed, équivalent système d'Oswald (voir plus bas) |
| Logotype (p. 8-10) | version couleurs à privilégier ; réserve blanche uniquement sur une couleur de la palette ; pas de cadre ni de déformation | logo blanc sur le bandeau rouge ; logo couleurs en bas, centré (p. 27) |
| Formes et motif (p. 21-22) | arche, nœud (deux demi-disques) et heptagone ; motif dans un angle, bord en diagonale | motif blanc dans l'angle du bandeau ; numéros des rubriques dans une arche ; formes devant les chiffres de la Une et dans le sommaire |
| Mix photo / forme (p. 23) | photo associée à une forme | photo principale des ouvertures découpée en arche |
| Titres (toute la charte) | capitales, filet court, numérotation « 01. » | titres de rubrique en capitales avec filet court, numéros « 01 » |

### Pourquoi pas Josefin Sans et Oswald ?

Ce sont des polices Google Fonts, donc téléchargées en ligne : interdit ici (Gmail et
l'impression doivent rendre la même chose sur tous les postes). La charte prévoit elle-même
**Century Gothic** comme substitution (p. 15) ; elle est installée avec Microsoft Office.
Pour Oswald (condensée), l'équivalent système le plus proche est **Bahnschrift Condensed**,
fournie avec Windows 10 et 11. Sur un poste sans ces polices, les replis prennent le relais
(URW Gothic, Trebuchet MS, Arial ; Arial Narrow).

### Contrastes : où va chaque couleur

Le rouge Carmila ne contraste pas assez avec le blanc pour du petit texte (3,8:1, minimum
4,5:1). Il est donc réservé au **grand texte** (nom et mois du bandeau, numéros des
rubriques : minimum 3:1) et aux éléments graphiques (bandeau, filets, formes). Les titres et
les liens sont en **vert foncé** (9,77:1), le texte en **gris charte** (7,01:1). Le turquoise,
l'orange et le jaune servent de fond aux formes ; le numéro écrit dessus prend
automatiquement la couleur la plus lisible (blanc ou vert foncé).

## Valeurs modifiables

| Clé | Rôle | Format |
| --- | --- | --- |
| `name` | Nom affiché dans le bandeau | texte, 80 caractères au plus |
| `tagline` | Phrase sous le bandeau | texte |
| `colors.primary` | Bandeau, filets, grands éléments (jamais de petit texte) | `#RRGGBB` |
| `colors.secondary` | Titres, liens, chiffres de la Une | `#RRGGBB` |
| `colors.text` | Texte courant | `#RRGGBB` |
| `colors.muted` | Sources, dates, légendes | `#RRGGBB` |
| `colors.background` | Fond ; **à laisser blanc** (`#FFFFFF`) ; aussi la couleur du texte du bandeau | `#RRGGBB` |
| `colors.surface` | Fond des encadrés (Une, rencontres, plans) | `#RRGGBB` |
| `colors.border` | Séparateurs fins | `#RRGGBB` |
| `colors.opportunity` / `opportunity_text` | Fond et texte du badge « Opportunité emplacements » | `#RRGGBB` |
| `section_colors.*` | Couleur d'accent de la Une et de chaque rubrique | `#RRGGBB` |
| `fonts.body` / `headings` / `labels` | Texte, titres, chiffres et petits libellés | polices **système**, liste terminée par `sans-serif`, `serif` ou `monospace` |
| `logo` | Logo couleurs, pour fond blanc (pied de page) | PNG ou JPEG, chemin relatif au dossier du projet |
| `logo_reverse` | Logo en réserve blanche, pour le bandeau | PNG ou JPEG (de préférence PNG transparent) |
| `logo_alt` | Texte alternatif des logos | texte |
| `footer_text` | Texte du pied de page | texte, 300 caractères au plus |
| `section_titles.*` | Titre de la Une et des 6 rubriques | texte, 80 caractères au plus |

Notes :

- **Couleurs** : toujours 6 chiffres hexadécimaux précédés de `#`, entre guillemets
  (`"#EF4050"`). Les formats courts (`#E00`) ou les noms (`red`) sont refusés.
- **Polices** : uniquement des polices installées sur les postes. Les noms à espaces se
  mettent entre apostrophes : `"'Century Gothic', Arial, sans-serif"`.
- **Logos** : `config/assets/logo-carmila.png` et `config/assets/logo-carmila-blanc.png`
  ont été extraits de la charte (p. 8 et p. 1), sur fond transparent, aux couleurs
  `#EF4050` et `#FFCC32`. Si la communication fournit les fichiers officiels, déposez-les
  dans `config/assets/` sous le même nom (ou changez `logo` / `logo_reverse`). Taille
  d'affichage : 170 px de large dans le bandeau, 120 px en pied de page (au-dessus des
  10 mm minimum de la charte).

## Vérifier après une modification

1. Enregistrez `config/theme.yaml` (encodage UTF-8).
2. Ouvrez l'écran **Thème** depuis la page d'accueil (inutile de relancer l'application :
   le fichier est relu à chaque affichage).
3. En cas d'erreur, le message indique la clé fautive et la valeur lue, par exemple :
   « la couleur « colors.primary » doit être au format #RRGGBB (ex. #EF4050) ; valeur
   lue : '#12' » ou « logo introuvable : config/assets/logo.png ».
4. Lisez le tableau **Contrastes** : chaque ligne indique son minimum (4,5:1 pour le texte
   courant, 3:1 pour le grand texte, WCAG AA). En dessous, un avertissement s'affiche (non
   bloquant : l'aperçu reste disponible, mais le texte sera difficile à lire, surtout
   imprimé). Exemple : un gris `#777777` sur blanc donne 4,48:1, juste sous le minimum.
5. Ouvrez l'**Aperçu** d'un mois (par exemple la démonstration, janvier 2000).

## Contrastes vérifiés

| Association | Minimum |
| --- | --- |
| Texte sur le fond, et sur les encadrés | 4,5:1 |
| Texte secondaire sur le fond, et sur les encadrés | 4,5:1 |
| Titres et liens (`secondary`) sur le fond | 4,5:1 |
| Badge opportunité (texte sur son fond) | 4,5:1 |
| Grand texte du bandeau (couleur du fond) sur la couleur principale | 3:1 |
| Numéro de chaque rubrique sur sa couleur d'accent | 3:1 |
