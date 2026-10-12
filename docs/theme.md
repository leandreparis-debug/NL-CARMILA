# Thème de la newsletter : appliquer la charte Carmila

Toute la charte graphique de la newsletter tient dans un seul fichier :
**`config/theme.yaml`**. Les gabarits (`news_franchise/templates/newsletter/_*.html`) et la
feuille de style (`news_franchise/static/newsletter.css`) n'utilisent que ces valeurs : il
n'y a rien d'autre à modifier pour changer l'apparence.

Les valeurs livrées sont **provisoires** (bleu marine sobre, Arial, logo texte généré) et
marquées « À remplacer par la charte Carmila » dans le fichier.

## Valeurs à changer

| Clé | Rôle | Format |
| --- | --- | --- |
| `name` | Nom affiché (texte alternatif du logo, pied de page) | texte, 80 caractères au plus |
| `tagline` | Phrase sous le logo | texte |
| `colors.primary` | Titres, liens, bandeaux de rubrique, chiffres de la Une | `#RRGGBB` |
| `colors.secondary` | Filets sous l'en-tête et au-dessus du pied de page | `#RRGGBB` |
| `colors.text` | Texte courant | `#RRGGBB` |
| `colors.muted` | Texte secondaire : sources, dates, légendes | `#RRGGBB` |
| `colors.background` | Fond de la newsletter ; **à laisser blanc** (`#FFFFFF`) pour l'impression et l'e-mail | `#RRGGBB` |
| `colors.border` | Bordures et séparateurs | `#RRGGBB` |
| `colors.opportunity` | Badge « Opportunité emplacements » | `#RRGGBB` |
| `fonts.body` / `fonts.headings` | Polices du texte et des titres | liste de polices **système**, terminée par `sans-serif`, `serif` ou `monospace` |
| `logo` | Logo en tête de la newsletter | chemin d'un PNG ou JPEG, relatif au dossier du projet |
| `footer_text` | Texte du pied de page | texte, 300 caractères au plus |
| `section_titles.*` | Titre de la Une et des 6 rubriques | texte, 80 caractères au plus |

Notes :

- **Couleurs** : toujours 6 chiffres hexadécimaux précédés de `#`, entre guillemets
  (`"#E2001A"`). Les formats courts (`#E00`) ou les noms (`red`) sont refusés.
- **Polices** : uniquement des polices installées sur les postes (Arial, Helvetica,
  Verdana, Georgia, « Segoe UI »…). Pas de police téléchargée : Gmail et l'impression
  doivent rendre la même chose partout. Si la charte impose une police propriétaire,
  choisissez la police système la plus proche. Les noms à espaces se mettent entre
  apostrophes : `"'Segoe UI', Arial, sans-serif"`.
- **Logo** : déposez le fichier dans `config/assets/` (par exemple
  `config/assets/logo-carmila.png`), puis indiquez `logo: config/assets/logo-carmila.png`.
  Format conseillé : PNG sur fond transparent ou blanc, environ 600 × 120 px ; il est
  affiché au plus à 360 × 80 px. Le logo provisoire (`config/assets/logo-provisoire.png`)
  est recréé automatiquement s'il est supprimé ; tout autre logo introuvable est une
  erreur.

## Vérifier

1. Enregistrez `config/theme.yaml` (encodage UTF-8).
2. Ouvrez l'écran **Thème** depuis la page d'accueil (inutile de relancer l'application :
   le fichier est relu à chaque affichage).
3. En cas d'erreur, le message indique la clé fautive et la valeur lue, par exemple :
   « la couleur « colors.primary » doit être au format #RRGGBB (ex. #1D3557) ; valeur
   lue : '#12' » ou « logo introuvable : config/assets/logo-carmila.png ».
4. Lisez le tableau **Contrastes** : chaque association doit atteindre **4,5:1** (niveau
   WCAG AA pour le texte courant). En dessous, un avertissement s'affiche (non bloquant :
   l'aperçu reste disponible, mais le texte sera difficile à lire, surtout imprimé).
5. Ouvrez l'**Aperçu** d'un mois (par exemple la démonstration, janvier 2000) pour juger
   le rendu.

## Contrastes vérifiés

| Association | Pourquoi |
| --- | --- |
| Texte sur le fond | texte courant |
| Texte secondaire sur le fond | sources, dates, légendes |
| Titres et liens (couleur principale) sur le fond | titres d'articles, liens, chiffres de la Une |
| Texte des bandeaux sur la couleur principale | les titres de rubrique sont écrits dans la couleur du fond (blanc) sur un bandeau de couleur principale |
| Badge opportunité sur le fond | badge « Opportunité emplacements » |

La couleur `text` n'est jamais écrite sur la couleur principale : c'est pourquoi cette
association n'est pas vérifiée. Exemple de seuil : un gris `#777777` sur blanc donne
4,48:1, juste en dessous du minimum ; `#5B6573` (valeur provisoire) donne 5,91:1.

Si la couleur principale de la charte est claire (jaune, rouge vif…), le contraste des
titres sur fond blanc et celui des bandeaux seront probablement insuffisants : prenez une
variante plus foncée de la couleur pour `primary` et gardez la couleur vive pour
`secondary` (filets).
