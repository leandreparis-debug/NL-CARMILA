# News Franchise

Application locale qui prépare chaque mois la **newsletter interne de Carmila Franchise** :

1. collecte automatique de la veille (flux RSS) ;
2. relecture et sélection des articles dans une interface web locale ;
3. ajout de contenu interne ;
4. deux sorties : un e-mail HTML (brouillon Gmail, créé via un script Google Apps Script) et une version A4 imprimable.

L'application est mono-utilisateur, fonctionne uniquement sur le poste (adresse `127.0.0.1`) et **n'utilise aucune IA** : aucun appel à un modèle de langage, aucun résumé généré.

> **État actuel (v0.1.0)** : socle technique, diagnostic des sources, base de données locale, collecte de la veille, détection des franchisés et opportunités, relecture et contenu interne, aperçu aux couleurs de la charte Carmila, e-mail Gmail (brouillon créé par un script Apps Script et l'API Gmail, images comprises). À venir : la version A4 imprimable.

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
| `NF_DRIVE_DIR` | dossier Google Drive synchronisé (facultatif) où copier le paquet de l'e-mail | vide (copie manuelle) |
| `NF_BROWSER` | navigateur (Edge ou Chrome) qui fabrique le PDF à imprimer | vide (recherche automatique) |

Une valeur invalide arrête l'application avec un message qui nomme la variable fautive. Le fichier `.env` n'est pas versionné : n'y mettez rien qui doive être partagé. Aucun secret n'est écrit dans le code.

## Données

### Base de données

Toutes les données de la newsletter (actualités retenues, franchisés, ouvertures, rencontres, historique des collectes) sont dans une base SQLite locale :

```
%LOCALAPPDATA%\NewsFranchise\db\news_franchise.sqlite3
```

Elle est créée, puis mise à jour (migrations), automatiquement au lancement de l'application. Les photos des ouvertures sont dans `photos\` ; la base ne stocke que leur nom. Le schéma et les règles (aucun lien inventé, Une calculée à la volée…) sont décrits dans [`docs/data-model.md`](docs/data-model.md).

### Sauvegarder

1. Fermez l'application (fenêtre noire de `lancer.bat`).
2. Copiez **tout le dossier** `%LOCALAPPDATA%\NewsFranchise\db\` (et `photos\` pour les photos) vers un emplacement de sauvegarde, par exemple Google Drive.

Copiez le dossier entier, pas seulement le fichier `.sqlite3` : si l'application n'a pas été fermée proprement, les fichiers `-wal` et `-shm` qui l'accompagnent contiennent les dernières modifications. Pour restaurer, remettez le dossier à sa place, application fermée.

### Modifier la liste des enseignes

Le référentiel des enseignes suivies est le fichier **`config\enseignes.yaml`** (nom, secteur, autres écritures du nom). Pour le modifier :

1. ouvrez-le avec le Bloc-notes et respectez l'indentation (2 espaces, pas de tabulation) ;
2. ajoutez, corrigez ou retirez une enseigne (champs `name`, `sector`, `aliases`) ;
3. relancez l'application : la base est synchronisée au démarrage.

Une enseigne retirée du fichier n'est jamais effacée de la base (son historique est conservé) : elle n'est simplement plus suivie. En cas d'erreur dans le fichier (nom manquant, doublon, indentation), l'application ne démarre pas et indique la ligne et l'enseigne fautives.

**À vérifier** : les secteurs ont été saisis à titre indicatif. Celui de « Mira Mira » est à compléter.

## Collecter la veille

La collecte lit les sources activées dans `config\sources.yaml` (flux RSS des sites et, si activé, Google Actualités pour chaque enseigne suivie). Elle ne garde que les articles **publiés pendant le mois choisi** (heure de Paris) et les classe :

- **rubrique 2** (actualités des enseignes) si le titre ou le résumé cite une enseigne de `config\enseignes.yaml` (nom ou autre écriture) ;
- **rubrique 1** (nouvelles franchises et développement) sinon, s'il contient un terme de développement en franchise de `config\regles_veille.yaml` ;
- les autres articles sont écartés.

Pour chaque article retenu, elle enregistre le titre, la source, la date, le **lien d'origine** (jamais inventé) et les premières lignes de l'article (environ 300 caractères, copiées telles quelles depuis la page, jamais reformulées). Tout le texte venant des sites est converti en texte brut.

### Lancer une collecte

- **Depuis l'application** : bouton **Collecter la veille** sur la page d'accueil. Choisissez le mois (par défaut le mois précédent, puisque la newsletter est préparée en début de mois pour le mois écoulé) puis **Lancer la collecte**. La page de suivi se met à jour toute seule, puis affiche le bilan.
- **En double-cliquant sur `collecter_veille.bat`** : il demande le mois (Entrée = mois précédent), puis affiche l'avancement et le bilan.
- **En ligne de commande** :

  ```bat
  .venv\Scripts\python.exe -m news_franchise.tools.collect --month 2026-10
  ```

Une seule collecte peut tourner à la fois ; une deuxième demande est refusée avec un message. Relancer la collecte d'un mois **ajoute uniquement les nouveaux articles** : la sélection, les corrections et l'ordre déjà faits ne sont jamais modifiés.

Prérequis : `config\sources.yaml` doit exister (voir « Tester les sources de veille »). S'il manque, la collecte ne démarre pas et l'application explique comment le créer.

### Lire le bilan

| Ligne | Signification |
|---|---|
| Articles ajoutés, rubrique 1 / 2 | Nouveaux articles enregistrés, prêts à être relus |
| Doublons ignorés | Article déjà présent ce mois-ci : même lien (après nettoyage des paramètres `utm_*`…) ou titre quasi identique pour la même enseigne |
| Articles hors période | Publiés en dehors du mois choisi |
| Articles sans date | Le flux ne donne pas de date : écartés, faute de pouvoir vérifier le mois |
| Articles hors sujet | Ni enseigne suivie, ni terme de développement en franchise |
| Par source | Entrées lues et articles ajoutés pour chaque source configurée |

### Si une source est en erreur

Une source en erreur n'arrête pas la collecte : les autres sources sont traitées, le bilan indique « Terminée, avec des sources en erreur » et donne la raison en français (ex. « Le site n'a pas répondu à temps », « Le site a refusé l'accès (HTTP 403) »).

1. Relancez la collecte un peu plus tard : seuls les articles manquants seront ajoutés.
2. Si l'erreur persiste plusieurs jours, relancez `diagnostiquer_sources.bat` pour vérifier la source, puis désactivez-la (`enabled: false`) dans `config\sources.yaml` si elle n'est plus exploitable.
3. Le détail technique est dans `%LOCALAPPDATA%\NewsFranchise\logs\news_franchise.log`.

### Ajuster le tri

Les listes de mots-clés sont dans **`config\regles_veille.yaml`** (commenté) :

- `development_terms` : termes qui envoient un article en rubrique 1 ;
- `exclusions` : expressions à ne pas compter (« franchise d'assurance », « franchise de TVA »…).

Pour une enseigne dont le nom est aussi un mot courant, mettez `case_sensitive: true` dans `config\enseignes.yaml` : la majuscule initiale sera exigée (c'est le cas d'Adopt, pour ne pas confondre avec « adopter »). Les changements s'appliquent aux collectes suivantes ; les articles déjà collectés ne sont pas reclassés.

## Relire la newsletter

Une fois la veille collectée, la relecture permet en quelques minutes de choisir ce qui ira dans la newsletter, de corriger, d'ordonner et de valider les franchisés.

### Pas à pas

1. **Accueil → Relire.** La page « Newsletters » liste les mois, du plus récent au plus ancien, avec leur statut (Brouillon, Relue, Exportée) et le nombre d'éléments retenus. Cliquez sur **Relire** devant un mois, ou choisissez un mois puis **Ouvrir ou créer ce mois**.
2. **Trois onglets** :
   - *Rubrique 1 — Marché de la franchise* ;
   - *Rubrique 2 — Nos enseignes* ;
   - *Rubrique 5 — Franchisés identifiés*.

   Chaque onglet affiche un compteur « retenus / limite ». Il passe **en orange** quand la limite est dépassée : c'est un avertissement, rien n'est bloqué. Un rappel indique que la version imprimée doit tenir en 4 pages A4.
3. **Filtres** :
   - articles : *Tout*, *Retenus*, *Non retenus*, *Opportunités* ;
   - franchisés : *Tout*, *Validés*, *À valider*, *Écartés*.
4. **Vue compacte.** Chaque article tient sur une ligne : rang, bouton **Retenir**, enseigne, titre, source, date, badge « Opportunité ».
   - **Modifier** déplie le formulaire complet de l'article.
   - **Tout déplier / Tout replier** ouvre ou ferme tous les formulaires.
5. **Retenir.** Un seul bouton, sur la ligne de l'article :
   - **Retenir** pour garder l'article dans la newsletter ;
   - **✓ Retenu — ne plus retenir** pour l'en retirer (il reste visible, en grisé).
6. **Ordonner** :
   - **⤒ En tête**, **↑ Monter**, **↓ Descendre**, **⤓ En fin** ;
   - ou tapez un numéro dans **Rang**, puis **Placer**. Un numéro trop grand place l'article en dernier.
   - **Ne retenir que les N premiers** (N = limite de la rubrique) retient les N premiers articles dans l'ordre affiché et retire les suivants.
7. **Corriger** (dans **Modifier**) :
   - **Titre** ;
   - **Enseigne** (les 15 enseignes, ou « Autre… » avec un nom libre) ;
   - **Secteur**, **Date**, **Source** ;
   - **Premières lignes** : elles peuvent être coupées ou corrigées, **pas réécrites**, elles doivent rester fidèles à l'article ;
   - la case **Opportunité**, puis **Enregistrer cet article**.

   Si le repère « opportunité » a été posé automatiquement, la phrase qui l'a déclenché est affichée. Une fois modifié à la main, la détection n'y touche plus. **Le lien de l'article n'est pas modifiable.**
8. **Rien ne se perd.**
   - Une carte modifiée et pas encore enregistrée affiche « Modifications non enregistrées ».
   - Quitter la page ou changer d'onglet à ce moment-là fait apparaître une demande de confirmation du navigateur.
   - Si un enregistrement est refusé (titre vide, date impossible…), la page revient avec **toute votre saisie** et le message à côté du champ à corriger.
9. **Changer de rubrique** (dans **Modifier**) : **Déplacer vers la rubrique 2** (l'enseigne est alors obligatoire) ou **vers la rubrique 1**. L'article se place en fin de la rubrique choisie.
10. **Supprimer…** demande une confirmation, puis efface l'article. Pour l'écarter simplement, préférez « Ne plus retenir ».
11. **+ Ajouter un article à la main** : collez le lien d'un article trouvé vous-même, puis **Vérifier le lien**. L'application lit le titre et les premières lignes, vous complétez le reste, puis vous enregistrez.
    - Un lien qui ne répond pas, ou qui ne commence pas par http(s), est refusé.
    - Si le site **refuse la lecture automatique** (protection anti-robot) : ouvrez le lien dans votre navigateur, saisissez titre et premières lignes, puis cochez **« J'ai ouvert ce lien dans mon navigateur et il affiche bien l'article »**. L'article porte alors la mention **« Lien vérifié par l'utilisateur »**.
12. **Onglet Franchisés.** Chaque fiche montre le nom, l'enseigne, le lieu, le nombre de points de vente, la source et l'**extrait qui justifie la détection**.
    - **Fiche complète / partielle / incomplète** indique les informations trouvées dans l'article, **pas** la fiabilité de la détection : vérifiez toujours l'extrait.
    - **Valider** garde la fiche dans la newsletter.
    - Toute correction (**Modifier**, puis **Enregistrer ce franchisé**) est définitive : la détection n'y touchera plus.
    - **Supprimer…** écarte une suggestion : elle n'est plus reproposée. Elle se retrouve dans le filtre **Écartés**, où **Restaurer** la remet en suggestion à valider. Une fiche saisie à la main est, elle, supprimée définitivement.
    - **+ Ajouter un franchisé à la main** exige le lien de l'article source, qui est vérifié.
13. **Marquer comme relue** (en haut à droite) passe la newsletter au statut « Relue ». Des avertissements s'affichent si une rubrique dépasse sa limite ou si aucun franchisé n'est validé. **Repasser en brouillon** permet de revenir en arrière.

Après chaque action, un message confirme ce qui a été fait, ou explique pourquoi c'est refusé, et la page revient sur l'élément concerné. Tout fonctionne sans JavaScript et au clavier : touche Tab, avec un lien « Aller au contenu » en premier.

### Limites par rubrique

Les limites sont dans **`config\limites.yaml`** (commenté) : rubrique 1 = 6, rubrique 2 = 8, franchisés = 5, ouvertures = 4, pages = 4 au départ. Modifiez le fichier puis rechargez la page : inutile de relancer l'application. Si le fichier est absent, ces valeurs s'appliquent ; s'il est invalide, un message l'indique en haut de la page.

### Essayer sans collecte réelle : la démonstration

```bat
.venv\Scripts\python.exe -m news_franchise.tools.demo
```

Crée la newsletter fictive de **janvier 2000**, avec des articles marqués « [DÉMO] » dont les liens mènent à `example.com`. Aucun autre mois n'est touché. `--reset` la recrée à l'identique.

### Sécurité

Formulaires protégés par jeton, adresse contrôlée, textes des sites toujours affichés comme du texte, liens non modifiables : voir [`docs/securite.md`](docs/securite.md).

## Ajouter le contenu interne

Le contenu interne se saisit dans l'écran du mois, à côté de la veille. Les onglets suivent l'ordre de la newsletter :

**Une** · **1. Marché** · **2. Nos enseignes** · **3. Ouvertures** · **4. Enseignes rencontrées** · **5. Franchisés** · **6. Plans de développement**

Le bouton **Contenu interne** de l'accueil ouvre directement l'onglet « 3. Ouvertures » du mois en préparation, c'est-à-dire le plus récent au statut Brouillon.

### La Une

Elle affiche trois chiffres :
- le nombre d'**ouvertures** ;
- le nombre d'**enseignes rencontrées**, chaque enseigne comptée une fois ;
- le nombre de **franchisés identifiés**, seulement les fiches validées.

Ils sont **calculés automatiquement** à partir des rubriques 3, 4 et 5 : il n'y a rien à saisir. Un lien sous chaque chiffre mène à la rubrique concernée. S'il reste des franchisés à valider, la Une le signale : ils ne sont pas encore comptés.

### 3. Ouvertures (avec photos)

1. **+ Ajouter une ouverture** :
   - l'enseigne (une des 15, ou « Autre… » avec son nom) ;
   - le lieu (centre commercial et ville, obligatoire) ;
   - la date d'ouverture (facultative) ;
   - une description courte (400 caractères au plus, un compteur l'indique).

   Si la date ne tombe ni dans le mois de la newsletter ni dans le mois précédent, un avertissement s'affiche, sans bloquer.
2. Sur la fiche de l'ouverture, **Ajouter des photos** : choisissez une ou plusieurs photos (JPEG, PNG ou WebP), puis **Envoyer les photos**.
   - 3 photos au maximum par ouverture (réglable dans `config\limites.yaml`).
   - 15 Mo au maximum par envoi. Au-delà, un message invite à envoyer les photos une par une.
3. Pour chaque photo :
   - une **légende** facultative ;
   - **Choisir comme photo principale** : la photo principale, marquée ★, est la première et sera utilisée en priorité dans les exports ;
   - **Supprimer…**, avec confirmation.
4. **Modifier**, **⤒ En tête / ↑ / ↓ / ⤓ En fin / Rang** et **Supprimer…** fonctionnent comme pour les articles. Supprimer une ouverture supprime aussi ses photos.

Les photos sont **traitées automatiquement** à l'envoi :
- redressées selon l'orientation du téléphone ;
- réduites à 1600 pixels sur le grand côté ;
- enregistrées en JPEG ;
- **débarrassées de leurs métadonnées**, dont la position GPS.

Elles sont rangées dans `%LOCALAPPDATA%\NewsFranchise\photos\AAAA-MM\`, sous un nom généré par l'application. Un fichier qui n'est pas une vraie photo (un document renommé en .jpg, par exemple) est refusé.

### 4. Enseignes rencontrées

- **Ajouter une enseigne rencontrée** : l'enseigne (la liste des 15 enseignes est proposée pendant la frappe, mais tout nom est accepté), la date et un **résumé du rendez-vous** pour les équipes (jusqu'à 1 000 caractères, retours à la ligne conservés), tous deux facultatifs. Dans la newsletter, une rencontre avec un résumé prend toute la largeur.
- **Ajout rapide** : collez une liste, **une enseigne par ligne**.
  - Les lignes vides sont ignorées.
  - Les enseignes déjà présentes ce mois-ci sont ignorées et signalées, sans tenir compte des majuscules ni des accents : « Pokawa » et « pokawa » sont un doublon.
- **Modifier**, déplacements et **Supprimer…** comme ailleurs.

### 6. Plans de développement

Saisissez **jusqu'à 6 liens**, par exemple un par région, chacun avec son **libellé** (« Plans Île-de-France »…) ; un libellé vide donne « Voir les plans de développement ». Ce sont souvent des documents SharePoint ou Google Drive. Les lignes vides sont ignorées ; la newsletter affiche un bouton par lien, dans l'ordre des lignes.

L'application vérifie seulement que chaque adresse commence par `http://` ou `https://`. Elle n'appelle jamais les liens, qui demandent souvent une connexion. Testez-les vous-même avec **Ouvrir**. **Retirer tous les liens** les enlève.

### Avant de marquer la newsletter comme relue

« Marquer comme relue » signale aussi, sans bloquer :
- l'absence d'ouverture ;
- l'absence d'enseigne rencontrée ;
- l'absence de lien vers les plans ;
- un nombre d'ouvertures supérieur à la limite (4 par défaut).

La démonstration (`python -m news_franchise.tools.demo`) contient maintenant aussi :
- 2 ouvertures avec des photos générées, marquées « DÉMO » ;
- 4 enseignes rencontrées ;
- un lien de plans vers `example.com`.

## Aperçu de la newsletter

Dans l'écran du mois, le bouton **Aperçu** (en haut à droite) affiche la newsletter telle
qu'elle sera publiée, en version imprimable : page blanche d'environ 800 px de large.

- **En-tête** : logo, phrase d'accroche, mois (« Octobre 2026 »).
- **À la une** : nombre d'ouvertures, d'enseignes rencontrées et de franchisés identifiés,
  toujours calculés ; chaque chiffre renvoie à sa rubrique.
- **Sommaire** : rubriques publiées avec leur nombre d'éléments.
- **Rubriques**, dans l'ordre de la relecture : seuls les articles **retenus** et les
  franchisés **validés** apparaissent. Une rubrique vide est masquée, et les rubriques
  publiées sont renumérotées sans trou (1, 2, 3…).
- Sous le titre de chaque article : un **QR code** du lien de l'article (pour la version
  papier), le badge **« Opportunité emplacements »** si besoin, la source, la date et
  l'extrait.
- Ouvertures : **photo principale** (choisie dans le contenu interne) et sa légende ; les
  autres photos en vignettes (chaque export pourra les retirer faute de place).
- Franchisés : le nombre de points de vente n'apparaît que s'il est connu.
- **Pied de page** : texte défini dans le thème.

Les dates sont écrites en français quel que soit le réglage de Windows, avec la convention
« 1er » pour le premier jour du mois (« 1er octobre 2026 », « 12 octobre 2026 »).

Les QR codes (correction d'erreur M) sont conservés dans `<données>\exports\qr\`, sous
un nom tiré de l'empreinte SHA-256 du lien : ils ne sont produits qu'une fois. Un QR code
n'est produit que pour un lien `http://` ou `https://`.

Le bouton **Imprimer** (dans l'aperçu, l'écran du mois et la page d'export) ouvre la boîte d'impression du navigateur : imprimante, ou « Enregistrer au format PDF ». L'impression donne déjà un A4 (la démonstration, au-dessus des limites par rubrique, fait 5 pages ; le A4 final de l'étape 10 devra tenir en 4) ; les exports e-mail et A4
arrivent dans les étapes suivantes et reprendront les mêmes gabarits
(`news_franchise/templates/newsletter/_*.html`).

## Exporter l'e-mail (Gmail)

Page d'accueil → **Exporter** (ou bouton **Exporter** de l'écran du mois) → **Préparer
l'e-mail**. L'application produit l'e-mail de la newsletter, adapté à Gmail (mise en page en
tableaux de 600 px, images jointes au message, version texte), et un **paquet**
`news-franchise-AAAA-MM.json`. Déposé dans le dossier **News Franchise** de Google Drive
(automatiquement si `NF_DRIVE_DIR` est renseigné dans `.env`), ce paquet est lu par le
script `apps_script/brouillon_gmail.gs`, qui crée un **brouillon Gmail** : il ne reste qu'à
ajouter les destinataires et envoyer. Rien n'est envoyé automatiquement, et l'application
ne stocke aucun identifiant Google.

L'e-mail porte un bouton **« Imprimer la newsletter (PDF) »** : un e-mail ne peut pas lancer
l'impression lui-même, le bouton ouvre donc la version PDF, que le lecteur imprime.
L'application fabrique ce PDF avec le navigateur du poste (Edge, installé avec Windows, ou
Chrome ; `NF_BROWSER` pour en indiquer un autre) ; le script le dépose dans le dossier Drive,
le partage en lecture aux personnes de l'organisation qui ont le lien, et le relie au bouton.

La page d'export affiche la taille du HTML (Gmail tronque au-delà de 102 Ko : un
avertissement s'affiche avant), les images jointes et l'e-mail tel qu'il sera reçu.
Installation du script (une fois) et marche à suivre : [`docs/email.md`](docs/email.md).

## Thème et charte graphique

Tout ce qui relève de la charte graphique est dans **`config/theme.yaml`** : nom, phrase
d'accroche, couleurs, couleur de chaque rubrique, polices, logos, pied de page et titres des
rubriques. Le thème applique la **charte Carmila 2023** (« Les fondamentaux de la
marque ») : bandeau rouge avec logo en réserve blanche et motif de formes géométriques,
rubriques numérotées « 01 » dans une arche, encadrés crème, titres en vert foncé, logo
couleurs en bas et centré. Détail des choix, et comment modifier une valeur :
[`docs/theme.md`](docs/theme.md).

Polices : la charte utilise Josefin Sans et Oswald, téléchargées en ligne, ce qui est exclu
ici ; on utilise **Century Gothic**, la substitution prévue par la charte, et
**Bahnschrift Condensed** (Windows) pour les chiffres et petits libellés.

L'écran **Thème** (bouton sur la page d'accueil) affiche le thème en lecture seule :
couleurs, couleurs des rubriques, polices, logos, chemin du fichier à modifier et
**vérification des contrastes** (4,5:1 pour le texte courant, 3:1 pour le grand texte).
Un contraste insuffisant donne un avertissement, sans bloquer ; une valeur invalide
(couleur qui n'est pas au format `#RRGGBB`, logo introuvable…) donne un message d'erreur
clair indiquant la clé à corriger.

## Franchisés et opportunités

Après chaque collecte, l'application propose automatiquement :

- un **repère « opportunité »** sur les articles où une enseigne cherche des emplacements (notamment en centre commercial) ;
- des **franchisés identifiés** (rubrique 5) : nom, enseigne(s), ville ou région, nombre de points de vente (vide s'il n'est pas dans l'article), source = l'article d'origine.

Chaque détection est justifiée par **la phrase de l'article** qui l'a déclenchée. Les franchisés sont des **suggestions à valider** ; leur niveau de confiance (haute, moyenne, basse) indique si la fiche est complète. Rien n'est inventé : sans nom dans l'article, aucune fiche n'est créée.

- **Relancer la détection** : bouton « Relancer la détection » sur la page « Collecter la veille », ou :

  ```bat
  .venv\Scripts\python.exe -m news_franchise.tools.detect --month 2026-10
  ```

  Un franchisé validé, modifié ou écarté et un repère « opportunité » modifié à la main ne sont jamais touchés.
- **Mesurer la fiabilité** sur un mois réel :

  ```bat
  .venv\Scripts\python.exe -m news_franchise.tools.evaluate_detection --month 2026-10
  ```

  Le rapport (`%LOCALAPPDATA%\NewsFranchise\reports\detection-…md`) liste chaque détection avec sa phrase et une case « juste / faux » à cocher, ainsi que les articles non marqués qui contiennent un terme (oublis possibles). Il sert à décider si le repère « opportunité » est assez fiable pour être gardé.
- **Ajuster les règles** : `config\regles_detection.yaml` (mots-clés, commenté) et `config\lieux_france.yaml` (villes, départements, régions). Fonctionnement, confiance et limites : [`docs/detection.md`](docs/detection.md).

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
├── collecter_veille.bat    # Collecte de la veille d'un mois
├── requirements.txt        # Dépendances d'exécution (versions exactes)
├── requirements-dev.txt    # Dépendances de test (inclut requirements.txt)
├── pyproject.toml          # Métadonnées du projet et configuration de pytest
├── .env.example            # Modèle de configuration commenté
├── .gitignore
├── .gitattributes          # Fins de ligne (CRLF pour les .bat)
├── README.md
├── apps_script/
│   ├── brouillon_gmail.gs  # Script Google Apps Script : brouillon Gmail depuis le paquet
│   └── appsscript.json     # Manifeste : service avancé Gmail API (facultatif à copier)
├── config/
│   ├── enseignes.yaml      # Référentiel des 15 enseignes suivies
│   ├── regles_veille.yaml  # Mots-clés de tri de la veille (rubrique 1, exclusions)
│   ├── regles_detection.yaml # Règles « opportunité » et franchisés
│   ├── lieux_france.yaml   # Régions, départements, grandes villes
│   ├── limites.yaml        # Limites éditoriales par rubrique
│   ├── theme.yaml          # Charte graphique de la newsletter (charte Carmila 2023)
│   ├── assets/             # Logos Carmila (couleurs, réserve blanche)
│   └── sources.example.yaml  # Format documenté de config/sources.yaml
├── docs/
│   ├── data-model.md       # Modèle de données et procédure de migration
│   ├── detection.md        # Détection des opportunités et des franchisés
│   ├── theme.md            # Charte Carmila appliquée au thème, valeurs modifiables
│   ├── email.md            # E-mail Gmail : préparation, script Apps Script, paquet
│   └── securite.md         # CSRF, contrôle du Host, échappement, liens non modifiables
├── news_franchise/         # Code de l'application
│   ├── __init__.py         # create_app(), routes, pages d'erreur, __version__
│   ├── __main__.py         # Point d'entrée : python -m news_franchise
│   ├── config.py           # Settings et load_settings()
│   ├── logging_setup.py    # Journal rotatif + console
│   ├── dates.py            # Noms de mois en français
│   ├── models.py           # Dataclasses (Newsletter, Article, Franchisee...)
│   ├── brand_catalog.py    # Lecture et validation de config/enseignes.yaml
│   ├── db/
│   │   ├── connection.py   # Connexion SQLite, migrations, intégration Flask
│   │   └── migrations/     # 0001_initial.sql...
│   ├── repositories/       # Fonctions d'accès aux données, une par table principale
│   ├── http_client.py      # Client HTTP poli (reprises, débit, robots.txt)
│   ├── sources/
│   │   ├── candidates.py   # Sources candidates et enseignes suivies
│   │   ├── discovery.py    # Découverte des flux d'un site
│   │   └── evaluation.py   # Évaluation d'un flux, Google Actualités, verdicts
│   ├── collect/            # Collecteur de veille
│   │   ├── config.py       # Lecture de sources.yaml et regles_veille.yaml
│   │   ├── feeds.py        # Lecture des flux (sites, Google Actualités)
│   │   ├── matching.py     # Détection des enseignes et des mots-clés, classement
│   │   ├── urls.py         # Normalisation des liens (dédoublonnage)
│   │   ├── excerpt.py      # Premières lignes et texte brut des articles
│   │   ├── runner.py       # Orchestrateur run_collection()
│   │   └── views.py        # Pages web /collecte
│   ├── detect/             # Détection : règles, phrases, lieux, opportunités, franchisés
│   ├── review/             # Relecture : limites, actions (service.py), pages (views.py)
│   ├── content/            # Contenu interne : photos.py (traitement), service.py, pages
│   ├── newsletter/         # Thème, formes de la charte, dates, QR codes, vue, aperçu,
│   │                       # e-mail Gmail (email.py) et pages d'export
│   ├── security.py         # Clé secrète, jeton CSRF, contrôle du Host et de l'origine
│   ├── fonts.py            # Police système pour les images générées (logo, démo)
│   ├── tools/
│   │   ├── diagnose_sources.py  # Outil de diagnostic des sources
│   │   ├── collect.py      # Collecte en ligne de commande
│   │   ├── detect.py       # Détection en ligne de commande
│   │   ├── evaluate_detection.py  # Rapport de fiabilité de la détection
│   │   └── demo.py         # Newsletter de démonstration (janvier 2000)
│   ├── templates/          # Gabarits Jinja2 ; newsletter/_*.html : gabarits communs
│   └── static/             # Feuilles de style (application, newsletter)
└── tests/
    ├── conftest.py         # Fixtures (données dans tmp_path, réseau interdit)
    ├── helpers.py          # Données de référence et simulation HTTP (respx)
    ├── fixtures/           # Pages HTML et flux RSS enregistrés
    ├── test_config.py
    ├── test_app.py
    ├── test_db.py
    ├── test_brands.py
    ├── test_repositories.py
    ├── test_collect_units.py
    ├── test_collect_runner.py
    ├── test_collect_web.py
    ├── test_detection.py   # dont les cas étiquetés de fixtures/detection_cases.yaml
    ├── test_review.py      # Interface de relecture et sécurité
    ├── test_content.py     # Contenu interne : Une, ouvertures, photos, rencontres, plans
    ├── test_newsletter.py  # Thème, dates, vue, QR codes, aperçu
    ├── test_email.py       # E-mail Gmail, paquet Apps Script, pages d'export
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
