# Modèle de données

Base SQLite locale : `<données>/db/news_franchise.sqlite3` (par défaut `%LOCALAPPDATA%\NewsFranchise\db\`).
Accès par `sqlite3` (bibliothèque standard, sans ORM), via les fonctions de `news_franchise/repositories/`, qui manipulent les dataclasses de `news_franchise/models.py`.

## Règles

1. **Aucun lien inventé.** Un article ou un franchisé n'existe en base qu'avec l'URL réelle de l'article d'origine. Toute URL stockée commence par `http://` ou `https://`. C'est contrôlé deux fois : à la construction des dataclasses (`ValueError`) et par une contrainte `CHECK` en SQL.
2. **La Une est calculée à la volée.** Nombre d'ouvertures, d'enseignes rencontrées et de franchisés **validés** : `newsletters.front_page_figures()` les calcule par requête. Ces chiffres ne sont jamais stockés.
3. **Photos stockées par nom relatif.** `opening_photos.file_name` est relatif au dossier `<données>/photos` (ex. `2026-10/ouverture-lyon.jpg`). Jamais de chemin absolu, de `\`, de `:` ni de `..` : contrôle en Python et en `CHECK` SQL.
4. **Dates en ISO 8601 (texte).** Date-heure en UTC avec fuseau (`2026-10-09T12:00:00+00:00`), date simple `AAAA-MM-JJ`. Le mois d'une newsletter est au format `AAAA-MM`.
5. **Requêtes toujours paramétrées.** Aucune donnée n'est concaténée dans le SQL. Seuls les noms de tables et de colonnes fixés dans le code le sont.
6. **Intégrité.** `PRAGMA foreign_keys = ON` à chaque connexion, journal `WAL`. Supprimer une newsletter supprime en cascade tout son contenu.
7. **Ordre d'affichage.** Les colonnes `position` (0, 1, 2…) sont propres à chaque liste (rubrique d'une newsletter, photos d'une ouverture…). Un ajout sans position va en fin de liste ; `reorder()` renumérote.

## Tables

```
newsletters ─┬─< articles >──── brands
             │       │
             │       └──(article_id, SET NULL)──< franchisees
             ├─< franchisees
             ├─< openings ─< opening_photos
             ├─< meetings
             └─< collection_runs
```
`─<` : « un à plusieurs ». Toutes les relations depuis `newsletters` (et `openings` → `opening_photos`) sont en `ON DELETE CASCADE`.

### `newsletters`: une newsletter par mois
| Colonne | Type | Règles |
|---|---|---|
| `id` | INTEGER | clé primaire |
| `month` | TEXT | `AAAA-MM`, unique, mois 01 à 12 |
| `status` | TEXT | `draft` (défaut), `reviewed`, `exported` |
| `development_plans_url` | TEXT | rubrique 6 ; nullable ; http(s) |
| `created_at`, `updated_at` | TEXT | ISO 8601 |

### `brands`: référentiel des enseignes (synchronisé depuis `config/enseignes.yaml`)
| Colonne | Type | Règles |
|---|---|---|
| `id` | INTEGER | clé primaire |
| `name` | TEXT | unique |
| `slug` | TEXT | unique (ex. `crepe-touch`) |
| `sector` | TEXT | secteur d'activité |
| `aliases` | TEXT | liste JSON des autres écritures du nom |
| `tracked` | INTEGER | 1 = suivie ; 0 = retirée du YAML (jamais supprimée) |

### `articles`: actualités de veille (rubriques 1 et 2)
| Colonne | Type | Règles |
|---|---|---|
| `id` | INTEGER | clé primaire |
| `newsletter_id` | INTEGER | → `newsletters`, CASCADE |
| `rubric` | INTEGER | 1 (nouvelles franchises) ou 2 (actualités des enseignes) |
| `brand_id` | INTEGER | → `brands`, nullable |
| `sector` | TEXT | nullable |
| `title` | TEXT | obligatoire |
| `published_at` | TEXT | nullable, ISO 8601 |
| `source_name` | TEXT | obligatoire (ex. « Toute la Franchise ») |
| `url` | TEXT | obligatoire, http(s) ; **unique par newsletter** (dédoublonnage) |
| `excerpt` | TEXT | premières lignes de l'article, nullable |
| `is_opportunity` | INTEGER | 1 = l'enseigne cherche des emplacements |
| `selected` | INTEGER | 1 (défaut) = retenu pour la newsletter |
| `position` | INTEGER | ordre dans la rubrique |
| `collected_at` | TEXT | date de collecte |

### `franchisees`: franchisés identifiés (rubrique 5)
| Colonne | Type | Règles |
|---|---|---|
| `id`, `newsletter_id` | INTEGER | → `newsletters`, CASCADE |
| `name` | TEXT | obligatoire |
| `brands` | TEXT | enseigne(s), texte libre |
| `location` | TEXT | ville ou région, nullable |
| `store_count` | INTEGER | nombre de points de vente, nullable (souvent inconnu), ≥ 0 |
| `source_name` | TEXT | obligatoire |
| `source_url` | TEXT | obligatoire, http(s) : l'article d'origine |
| `article_id` | INTEGER | → `articles`, nullable, `ON DELETE SET NULL` |
| `validated` | INTEGER | 0 (défaut) = détecté, 1 = validé par l'utilisateur |
| `position` | INTEGER | ordre d'affichage |

### `openings` et `opening_photos`: ouvertures du mois (rubrique 3)
`openings` : `id`, `newsletter_id` (CASCADE), `brand_name` (obligatoire), `location` (centre ou ville, obligatoire), `opening_date` (nullable), `description` (nullable), `position`.

`opening_photos` : `id`, `opening_id` (→ `openings`, CASCADE), `file_name` (nom relatif dans `photos/`), `caption` (nullable), `position`.

### `meetings`: enseignes rencontrées (rubrique 4)
`id`, `newsletter_id` (CASCADE), `brand_name` (obligatoire), `meeting_date` (nullable), `comment` (nullable), `position`.

### `collection_runs`: exécutions de la collecte
`id`, `newsletter_id` (CASCADE), `started_at`, `finished_at` (nullable), `status` (`running`, `success`, `partial`, `failed`), `stats` (JSON), `errors` (liste JSON de phrases en français).

### `schema_version`: migrations appliquées
`version` (clé primaire), `name` (nom du fichier), `applied_at`.

Index : clés étrangères, `(newsletter_id, rubric, position)` sur `articles`, `(newsletter_id, position)` sur les listes ordonnées.

## Fonctions de dépôt

| Module | Fonctions |
|---|---|
| `newsletters` | `get_or_create`, `get`, `get_by_id`, `list_all`, `set_status`, `set_development_plans_url`, `delete`, `front_page_figures` |
| `brands` | `sync_from_yaml`, `list_all`, `get`, `get_by_name`, `get_by_slug` |
| `articles` | `add` (renvoie `None` si l'URL existe déjà ce mois-ci), `get`, `list_for_rubric`, `update`, `set_selected`, `reorder`, `delete` |
| `franchisees` | `add`, `get`, `list_for_newsletter`, `update`, `set_validated`, `reorder`, `delete` |
| `openings` | `add`, `get`, `list_for_newsletter`, `update`, `reorder`, `delete`, `add_photo`, `get_photo`, `list_photos`, `reorder_photos`, `delete_photo` (supprime aussi le fichier) |
| `meetings` | `add`, `get`, `list_for_newsletter`, `update`, `reorder`, `delete` |
| `collection_runs` | `start`, `finish`, `get`, `last_for_newsletter` |

Chaque fonction prend la connexion en premier argument. Dans Flask, la connexion de la requête s'obtient par `news_franchise.db.connection.get_db()` ; ailleurs, par `get_connection(settings)` (à fermer après usage). Les connexions sont en autocommit ; pour grouper plusieurs écritures, utiliser `with transaction(conn):`.

## Ajouter une migration

Les migrations sont appliquées automatiquement au démarrage de l'application (`init_db`), chacune dans une transaction. Si l'une échoue, elle est entièrement annulée, la base reste dans sa version précédente et l'application refuse de démarrer avec un message clair.

1. Créer `news_franchise/db/migrations/000N_description.sql` : numéro suivant sur 4 chiffres, description en minuscules (`a-z`, chiffres, `_`).
2. N'y mettre que du SQL transactionnel (`CREATE`, `ALTER`, `INSERT`, `UPDATE`…). Pas de `BEGIN`/`COMMIT`, ni de `PRAGMA` ou `VACUUM`.
3. Ne jamais modifier une migration déjà livrée : en ajouter une nouvelle.
4. Pour modifier une contrainte (SQLite ne sait pas faire `ALTER COLUMN`) : créer la nouvelle table, copier les données, supprimer l'ancienne, renommer.
5. Mettre à jour les dataclasses, les dépôts, ce document, et ajouter un test (base vierge et base existante).
6. Lancer `pytest -q`.
