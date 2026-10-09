# News Franchise

Application locale qui prépare chaque mois la **newsletter interne de Carmila Franchise** :

1. collecte automatique de la veille (flux RSS) ;
2. relecture et sélection des articles dans une interface web locale ;
3. ajout de contenu interne ;
4. deux sorties : un e-mail HTML (brouillon Gmail, créé via un script Google Apps Script) et une version A4 imprimable.

L'application est mono-utilisateur, fonctionne uniquement sur le poste (adresse `127.0.0.1`) et **n'utilise aucune IA** : aucun appel à un modèle de langage, aucun résumé généré.

> **État actuel (v0.1.0)** : socle technique et outil de diagnostic des sources de veille. La page d'accueil s'affiche, les boutons des futures fonctions sont présents mais désactivés.

## Prérequis

- Windows 11 (le code fonctionne aussi sous Linux et macOS) ;
- Python 3.14 installé (avec le lanceur `py`, installé par défaut par l'installateur python.org) ;
- une connexion Internet lors de la première installation (téléchargement des dépendances).

Aucun droit administrateur n'est nécessaire.

## Installation et lancement

1. Placez le projet dans `Documents\NewsFranchise`.
2. Double-cliquez sur **`lancer.bat`**.

Au premier lancement, `lancer.bat` crée un environnement Python isolé (dossier `.venv`) et installe les dépendances. Il les réinstalle automatiquement si `requirements.txt` a été modifié depuis. Le navigateur s'ouvre ensuite sur <http://127.0.0.1:5000>.

Laissez la fenêtre noire ouverte tant que vous utilisez l'application ; fermez-la (ou faites `Ctrl+C`) pour l'arrêter.

Lancement manuel, équivalent :

```bat
.venv\Scripts\python.exe -m news_franchise
```

Si le port 5000 est déjà occupé, l'application l'indique (« L'application tourne peut-être déjà… ») et s'arrête : ouvrez simplement <http://127.0.0.1:5000>, ou changez de port via `NF_PORT`.

Vérification rapide : <http://127.0.0.1:5000/health> renvoie `{"status": "ok", "version": "0.1.0"}`.

## Emplacement des données

Les données de travail (base de données, photos, exports, rapports, journaux) sont stockées **hors du projet** :

| Système | Dossier par défaut |
|---|---|
| Windows | `%LOCALAPPDATA%\NewsFranchise` (ex. `C:\Users\leandre\AppData\Local\NewsFranchise`) |
| Linux / macOS | `~/.local/share/news-franchise` |

Sous-dossiers créés automatiquement : `db\`, `photos\`, `exports\`, `reports\`, `logs\`.

**Pourquoi pas dans Documents ?** Le dossier Documents est souvent synchronisé par OneDrive. Une base de données modifiée pendant une synchronisation peut être verrouillée, dupliquée (« conflit ») ou corrompue. `%LOCALAPPDATA%` n'est pas synchronisé et appartient à l'utilisateur.

Le journal de l'application se trouve dans `logs\news_franchise.log` (fichier rotatif : 1 Mo × 5 fichiers). En cas d'erreur, le détail technique y est consigné ; il n'est jamais affiché dans le navigateur.

## Configuration

La configuration se fait par variables d'environnement, ou plus simplement dans un fichier **`.env`** à la racine du projet :

1. copiez `.env.example` en `.env` ;
2. décommentez et modifiez les lignes voulues.

| Variable | Rôle | Défaut |
|---|---|---|
| `NF_DATA_DIR` | Dossier des données | `%LOCALAPPDATA%\NewsFranchise` |
| `NF_PORT` | Port local (1024 à 65535) | `5000` |
| `NF_DEBUG` | Mode debug Flask (`true`/`false`) | `false` |
| `NF_OPEN_BROWSER` | Ouvrir le navigateur au lancement | `true` |
| `NF_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |

Une valeur invalide arrête l'application avec un message qui nomme la variable fautive. Le fichier `.env` n'est pas versionné : n'y mettez rien qui doive être partagé. Aucun secret n'est écrit dans le code.

## Tester les sources de veille

La veille ne repose que sur des flux d'actualité **réellement exploitables** : aucun lien n'est inventé, une source n'est retenue que si elle fournit de vrais articles avec leur URL d'origine. L'outil de diagnostic teste depuis votre PC chaque source candidate (5 sites spécialisés et Google Actualités, interrogé pour chacune des 15 enseignes suivies). La liste est dans `news_franchise/sources/candidates.py`.

### Lancer le diagnostic

Double-cliquez sur **`diagnostiquer_sources.bat`** (connexion Internet requise, compter quelques minutes). La progression s'affiche dans la fenêtre, puis le rapport s'ouvre automatiquement.

Équivalent en ligne de commande :

```bat
.venv\Scripts\python.exe -m news_franchise.tools.diagnose_sources
.venv\Scripts\python.exe -m news_franchise.tools.diagnose_sources --only "AC Franchise"
.venv\Scripts\python.exe -m news_franchise.tools.diagnose_sources --only "O'Tacos"
.venv\Scripts\python.exe -m news_franchise.tools.diagnose_sources --no-google
```

L'outil est « poli » envers les sites : il s'annonce (`NewsFranchise/0.1.0 (veille interne)`), attend 1 seconde entre deux requêtes vers un même site, réessaie 2 fois au plus en cas d'erreur réseau, et respecte `robots.txt` pour les pages HTML. Une source en erreur n'interrompt jamais le diagnostic des autres.

### Où trouver le rapport

Dans le dossier `reports` des données (`%LOCALAPPDATA%\NewsFranchise\reports`) :

| Fichier | Contenu |
|---|---|
| `sources-AAAAMMJJ-HHMM.md` | Rapport lisible : tableau de synthèse puis détail par source (flux trouvés, chiffres, titres d'exemple, liens testés, erreurs) |
| `sources-AAAAMMJJ-HHMM.json` | Mêmes données, structurées |
| `sources.proposed.yaml` | Proposition de configuration (remplacée à chaque diagnostic) |

Le détail technique des erreurs est dans `logs\news_franchise.log`.

### Lire les verdicts

- **exploitable** : flux trouvé, au moins 80 % des articles ont un titre, une date et un lien, au moins un article publié depuis 30 jours, et les liens testés (3 par flux) répondent correctement.
- **partiel** : flux trouvé, mais un critère manque ; la raison indique lequel (ex. « aucune date de publication », « aucun article depuis 30 jours »).
- **inexploitable** : aucun flux trouvé, ou erreur (ex. « Le site a refusé l'accès (HTTP 403) »).

Pour Google Actualités, le verdict est donné par enseigne puis globalement ; une enseigne sans article sur 30 jours n'est pas un défaut de la source. La ligne « Résolution des liens » indique si les liens Google mènent directement à l'article de l'éditeur (`resolved`) ou restent des liens `news.google.com` (`google_link_only`) : ce n'est pas bloquant, ces liens ouvrent bien le vrai article chez le lecteur.

### Valider la proposition

1. Relisez `sources.proposed.yaml` en vous aidant du rapport. Seules les sources « exploitable » y sont activées (`enabled: true`) ; une source sans flux a `url: null`.
2. Ajustez si besoin (`enabled: true/false`, `note`), sans inventer d'URL : chaque adresse doit venir du diagnostic.
3. Copiez le fichier vers **`config\sources.yaml`** dans le dossier du projet. C'est ce fichier que la collecte utilisera.

Le format est documenté, champ par champ, dans `config/sources.example.yaml`.

## Tests

Sous Windows, double-cliquez sur **`tests.bat`** : il installe les dépendances de test (`requirements-dev.txt`) puis lance `pytest`.

Ou en ligne de commande :

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest -q
```

Les tests n'écrivent que dans des dossiers temporaires (`tmp_path`) : ils ne touchent ni vos données ni le dossier du projet. Ils n'accèdent jamais au réseau : les sites et flux sont simulés (`respx`) à partir des fichiers de `tests/fixtures/`, et toute connexion réelle est bloquée.

## Arborescence

```
NewsFranchise/
├── lancer.bat              # Lancement en double-clic (crée/met à jour .venv)
├── tests.bat               # Lancement des tests
├── diagnostiquer_sources.bat # Diagnostic des sources de veille
├── requirements.txt        # Dépendances d'exécution (versions exactes)
├── requirements-dev.txt    # Dépendances de test (inclut requirements.txt)
├── pyproject.toml          # Métadonnées du projet et configuration de pytest
├── .env.example            # Modèle de configuration commenté
├── .gitignore
├── .gitattributes          # Fins de ligne (CRLF pour les .bat)
├── README.md
├── config/
│   └── sources.example.yaml  # Format documenté de config/sources.yaml
├── news_franchise/         # Code de l'application
│   ├── __init__.py         # create_app(), routes, pages d'erreur, __version__
│   ├── __main__.py         # Point d'entrée : python -m news_franchise
│   ├── config.py           # Settings et load_settings()
│   ├── logging_setup.py    # Journal rotatif + console
│   ├── dates.py            # Noms de mois en français
│   ├── http_client.py      # Client HTTP poli (reprises, débit, robots.txt)
│   ├── sources/
│   │   ├── candidates.py   # Sources candidates et enseignes suivies
│   │   ├── discovery.py    # Découverte des flux d'un site
│   │   └── evaluation.py   # Évaluation d'un flux, Google Actualités, verdicts
│   ├── tools/
│   │   └── diagnose_sources.py  # Outil de diagnostic des sources
│   ├── templates/          # Gabarits Jinja2 (base, accueil, erreur)
│   └── static/             # Feuille de style
└── tests/
    ├── conftest.py         # Fixtures (données dans tmp_path, réseau interdit)
    ├── helpers.py          # Données de référence et simulation HTTP (respx)
    ├── fixtures/           # Pages HTML et flux RSS enregistrés
    ├── test_config.py
    ├── test_app.py
    ├── test_http_client.py
    ├── test_discovery.py
    ├── test_evaluation.py
    └── test_diagnose_sources.py
```

## Conventions de développement

- Code et noms techniques en anglais, textes affichés en français, docstrings en français.
- Annotations de type sur toutes les fonctions publiques.
- `pathlib` pour tous les chemins (code multiplateforme).
- Dépendances épinglées en version exacte (`==`).
