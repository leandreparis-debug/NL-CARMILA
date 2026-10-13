# E-mail Gmail : préparation et brouillon

L'application prépare l'e-mail de la newsletter ; un petit script **Google Apps Script**,
lancé depuis votre compte Google, en fait un **brouillon Gmail**. Rien n'est envoyé
automatiquement : vous ajoutez les destinataires, relisez et envoyez vous-même.

Pourquoi un script ? L'application tourne uniquement sur votre poste et ne se connecte à
aucun compte : pas de mot de passe ni de jeton Google à stocker. Le script, lui, s'exécute
dans votre compte Google, avec vos droits.

## Ce que contient l'e-mail

- Le même contenu que l'**Aperçu** : articles retenus, franchisés validés, ouvertures,
  enseignes rencontrées, lien des plans, Une et sommaire, aux couleurs de la charte.
- Une mise en page adaptée à Gmail : tableaux de 600 px, styles écrits dans chaque balise,
  ni SVG ni mise en page moderne (Gmail les ignore). Les formes de la charte et le motif
  du bandeau sont donc des images PNG.
- Les images (logos, motif, formes, photos des ouvertures) sont **jointes au message** et
  affichées dans le corps (« images intégrées ») : elles ne sont hébergées nulle part. Les
  photos sont recadrées et réduites (520 × 480 px pour la photo principale) : quelques
  dizaines de Ko chacune.
- Un lien « Lire l'article → » sous chaque article (pas de QR code dans l'e-mail : on
  clique). Une version texte accompagne le HTML (lecteurs sans HTML, notifications).
- Gmail **tronque** les messages dont le HTML dépasse 102 Ko (« [Message tronqué] ») ; la
  taille est affichée après chaque préparation, avec un avertissement au-delà de 92 Ko.
  Pour l'ordre de grandeur : le mois de démonstration (13 articles) fait environ 46 Ko.

## Préparer l'e-mail (chaque mois)

1. Page d'accueil → **Exporter** → le mois (ou bouton **Exporter** de l'écran du mois).
2. **Préparer l'e-mail**. La page affiche ensuite la taille du HTML, les images jointes,
   l'e-mail tel qu'il sera reçu, et le **paquet** `news-franchise-AAAA-MM.json`.
3. Le paquet doit se retrouver dans le dossier **News Franchise** de votre Google Drive :
   - automatiquement, si Google Drive pour ordinateur est installé et que la variable
     `NF_DRIVE_DIR` du fichier `.env` indique ce dossier (ex.
     `NF_DRIVE_DIR=G:\Mon Drive\News Franchise`) ;
   - sinon, téléchargez-le (lien « télécharger ») et déposez-le dans ce dossier depuis
     drive.google.com.
4. Ouvrez le projet Apps Script **News Franchise** et lancez **creerBrouillon** (bouton
   « Exécuter »). Le journal d'exécution indique le brouillon créé.
5. Dans Gmail, dossier **Brouillons** : ajoutez les destinataires, relisez, envoyez.

Les fichiers de l'export sont aussi dans `<données>\exports\AAAA-MM\email\` : l'e-mail à
ouvrir dans un navigateur (`news-franchise-AAAA-MM.html` et son dossier `images`) et le
paquet. Préparer à nouveau l'e-mail remplace l'export précédent du même mois.

## Installer le script (une seule fois)

1. Dans Google Drive, créez à la racine de **Mon Drive** un dossier nommé exactement
   **News Franchise** (ou changez `DOSSIER_DRIVE` en haut du script).
2. Ouvrez https://script.google.com, **Nouveau projet**, nommez-le « News Franchise ».
3. Remplacez le contenu de `Code.gs` par celui du fichier
   `apps_script/brouillon_gmail.gs` du projet, puis enregistrez.
4. Choisissez la fonction **creerBrouillon** et cliquez **Exécuter**. Google demande
   d'autoriser le script à lire Google Drive et à gérer Gmail (création du brouillon) :
   acceptez. Cette autorisation n'est demandée qu'une fois.

Si votre organisation Google Workspace bloque les scripts Apps Script ou les autorisations
demandées, l'administrateur doit les autoriser : le script ne peut pas s'en passer.

## Paquet : format

`news-franchise-AAAA-MM.json`, encodé en UTF-8 :

| Clé | Contenu |
| --- | --- |
| `format` | `news-franchise-email/1` (le script refuse un autre format) |
| `month`, `createdAt` | mois de la newsletter, date de préparation (UTC) |
| `subject` | objet : « News Franchise — Octobre 2026 » |
| `htmlBody` | HTML de l'e-mail ; les images y sont appelées par `cid:<nom>` |
| `textBody` | version texte |
| `images` | liste `{cid, fileName, mimeType, data}` (`data` en base64) |

## Limites connues

- Le script n'a pas pu être exécuté pendant le développement (aucun accès à un compte
  Google depuis l'environnement de test). Le paquet, lui, est vérifié par les tests
  (format, images, liens) ; le premier essai réel est à faire sur le mois de
  démonstration (janvier 2000).
- Le rendu a été vérifié dans un navigateur, pas dans l'application Gmail elle-même :
  quelques détails (arrondis, polices) peuvent varier selon le lecteur de messagerie.
  Outlook (bureau) ignore les arrondis : les arches y deviennent des rectangles.
- Les polices de la charte ne s'affichent que si elles sont installées chez le lecteur
  (Century Gothic, Bahnschrift) ; sinon Arial prend le relais.
