# Détection des opportunités et des franchisés

La détection repère, dans les articles collectés d'un mois :

- le **repère « opportunité »** : l'enseigne cherche des emplacements, notamment en centre commercial ;
- les **franchisés identifiés** (rubrique 5) : des multi-franchisés qui se développent.

**Il n'y a aucune IA.** La détection applique des listes de mots et des expressions régulières écrites dans `config/regles_detection.yaml`. Elle ne comprend pas le sens des phrases : elle reconnaît des formulations. Chaque détection garde **la phrase de l'article qui la justifie** et **les termes qui l'ont déclenchée**, pour être vérifiée en un coup d'œil. Aucun lien n'est créé : la source d'un franchisé est toujours l'article d'origine.

## Quand elle tourne

- automatiquement à la fin de chaque collecte ;
- avec le bouton **Relancer la détection** de la page « Collecter la veille » ;
- en ligne de commande : `python -m news_franchise.tools.detect --month 2026-10`.

Elle ne fait aucun appel réseau : elle relit le titre, les premières lignes et le texte (`body_text`) des articles déjà en base. Les articles de Google Actualités dont le lien n'a pas été résolu n'ont souvent que leur titre : la détection y est donc beaucoup moins efficace.

## Comment marchent les règles

Le texte est découpé en phrases (le titre compte comme une phrase). Les termes sont comparés sans tenir compte de la casse ni du type d'apostrophe, et doivent être des mots entiers.

### Repère « opportunité »

Un article est marqué si **une même phrase** contient :

- un terme de `search_terms` (« recherche des emplacements », « prospecte »…) **et** un terme de `place_terms` (« centre commercial », « retail park »…) ;
- **ou** une expression de `strong_terms` (« appel aux bailleurs »…), qui suffit seule.

Une phrase qui contient une expression d'`exclusions` (« ferme son magasin du centre commercial »…) est ignorée. Si les deux termes sont dans deux phrases différentes, l'article n'est pas marqué : c'est voulu, pour limiter les faux positifs.

### Franchisés

1. **Phrase déclencheuse** : une expression de `trigger_patterns` (« multi-franchisé », « franchisé de », « à la tête de cinq… », « exploite déjà 12… », « son 3e restaurant »…). Ici **les accents comptent** : « franchisé » déclenche, « franchise » non.
2. **Nom** : cherché dans la phrase déclencheuse, puis dans la phrase précédente et la suivante.
   - Société : « la société X », « le groupe X » (enregistré « Groupe X »), « X SAS/SARL ».
   - Personne : deux ou trois mots à majuscule (« Jean Dupont », « Marie-Claire Martin », « Thomas LEROY »). Les mots de `name_stopwords` (débuts de phrase, mois, titres), les noms d'enseignes et les noms de lieux sont ignorés.
   - **Sans nom, pas de fiche** : la phrase est comptée dans « phrases déclencheuses sans nom ».
3. **Enseigne(s)** : enseignes suivies citées dans la phrase (sinon dans ses voisines), plus l'enseigne de l'article (rubrique 2). À défaut, le nom propre qui suit « franchisé de ».
4. **Ville ou région** : un lieu de `config/lieux_france.yaml` (13 régions, 96 départements, 100 plus grandes villes) précédé de « à », « au », « en », « dans le/la/les/l' ».
5. **Nombre de points de vente** : un nombre en chiffres ou en lettres (de « deux » à « vingt ») suivi d'un mot de `store_units`. Sinon le champ reste vide.

Le même nom (sans tenir compte de la casse ni des accents) trouvé deux fois dans le mois ne donne qu'une fiche : la première source et sa phrase sont gardées, la seconde occurrence complète les champs vides.

## Comment lire la confiance

| Confiance | Ce qui a été trouvé |
|---|---|
| **haute** | nom + enseigne + nombre de points de vente |
| **moyenne** | nom + enseigne |
| **basse** | nom seul |

La confiance mesure la **complétude** de la fiche, pas la certitude que la personne est un franchisé. Une fiche « haute » peut être fausse : la phrase justificative permet de le voir. **Toute fiche est une suggestion à valider.**

## Le travail de l'utilisateur est protégé

Une nouvelle détection ne modifie jamais :

- un repère « opportunité » posé ou retiré à la main (`opportunity_source = manual`) ;
- un franchisé validé, modifié à la main (`edited`) ou écarté (`dismissed` : il n'est jamais recréé) ;
- une fiche saisie à la main (sans niveau de confiance).

Les suggestions jamais touchées sont recalculées ; celles que les règles ne trouvent plus sont retirées.

## Mesurer la fiabilité sur un mois réel

```bat
.venv\Scripts\python.exe -m news_franchise.tools.evaluate_detection --month 2026-10
```

Cette commande écrit `%LOCALAPPDATA%\NewsFranchise\reports\detection-2026-10-AAAAMMJJ-HHMM.md`, **sans modifier la base**. Le rapport contient :

1. chaque opportunité détectée : article, phrase, termes, une case **juste / faux** ;
2. chaque franchisé candidat, avec une case **juste / faux** ;
3. les phrases déclencheuses sans nom ;
4. les articles **non marqués** qui contiennent au moins un terme d'opportunité, avec une case **oubli**.

Ouvrez-le dans un éditeur de texte, cochez (`[x]`), puis comptez : précision = « juste » ÷ détections. Si la précision du repère « opportunité » reste faible sur deux ou trois mois, mieux vaut l'abandonner que d'induire les lecteurs en erreur.

## Ajuster un mot-clé

1. Ouvrez `config/regles_detection.yaml` (commenté, un exemple par liste).
2. Ajoutez ou retirez une ligne « - expression » dans la bonne liste.
   - Un faux positif récurrent se corrige par une **exclusion**.
   - Un oubli récurrent (vu dans la partie 4 du rapport) se corrige par un nouveau terme.
3. Relancez la détection, puis le rapport de fiabilité, pour vérifier.

Un fichier invalide (liste vide, doublon, expression régulière incorrecte) est refusé avec un message qui nomme la liste fautive, sans rien modifier en base. Attention : en YAML, `On`, `Oui`, `No`… doivent être écrits entre guillemets (`"On"`).

## Limites connues

- Pas de compréhension du sens : « Pokawa ne prospecte pas les centres commerciaux » est marqué (la négation n'est pas comprise).
- Les formulations non prévues ne sont pas détectées (« ambitionne d'ouvrir dans les malls », « cherche des pas-de-porte »…) : la partie 4 du rapport aide à les repérer.
- Les noms de personnes reposent sur les majuscules. Un nom d'une seule partie (« Karim ») n'est pas reconnu, ni un nom entièrement en capitales (« JEAN DUPONT » ; « Jean DUPONT » l'est). Un nom d'enseigne non suivie peut être pris pour un nom de personne (« Burger King », sauf juste après « franchisé de »).
- Les lieux absents de `config/lieux_france.yaml` (petites villes) ne sont pas reconnus : ajoutez-les au fichier.
- Le nombre trouvé peut être celui des ouvertures prévues et non des points de vente existants (« ouvrira cinq restaurants ») : vérifiez la phrase.
- Les articles réduits à leur titre (Google Actualités non résolu) donnent peu de résultats.
