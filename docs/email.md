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
- Un lien souligné **« voir la version à imprimer »** à côté de la phrase d'accroche, et
  « Version à imprimer (PDF) » en pied de page (voir plus bas).
- Gmail **tronque** les messages dont le HTML dépasse 102 Ko (« [Message tronqué] ») ; la
  taille est affichée après chaque préparation, avec un avertissement au-delà de 92 Ko.
  Pour l'ordre de grandeur : le mois de démonstration (13 articles) fait environ 46 Ko.

## Le lien « voir la version à imprimer »

Un e-mail ne peut pas lancer l'impression : Gmail et Outlook n'exécutent aucun programme
dans un message. Le lien ouvre donc la **version PDF** de la newsletter (la mise en page
imprimable de l'aperçu, en A4, avec les QR codes), que le lecteur imprime d'un clic.

1. **Préparer l'e-mail** fabrique aussi ce PDF, avec le navigateur du poste : Edge (installé
   avec Windows 10 et 11) ou Chrome, trouvés tout seuls ; la variable `NF_BROWSER` du fichier
   `.env` permet d'en indiquer un autre. Comptez quelques secondes.
2. Le PDF voyage dans le paquet. Le script `creerBrouillon` le dépose dans le dossier Drive
   **News Franchise** (il remplace celui du même mois), le **partage en lecture** puis met
   son adresse dans le lien et dans la version texte, avant de créer le brouillon.
3. Partage (constante `PARTAGE_PDF` en haut du script) : `'DOMAINE'` (par défaut) = les
   personnes de votre organisation qui ont le lien ; `'LIEN'` = toute personne qui a le lien ;
   `'AUCUN'` = vous seul (à partager vous-même). Si votre organisation interdit ce partage,
   le script s'arrête et le dit : changez `PARTAGE_PDF` ou partagez le fichier à la main.

Si aucun navigateur n'est trouvé, l'e-mail est préparé **sans** ce lien, et la page d'export
le signale. Le PDF est aussi enregistré à côté de l'export (`news-franchise-AAAA-MM.pdf`) et
s'ouvre depuis la page d'export.

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
ouvrir dans un navigateur (`news-franchise-AAAA-MM.html` et son dossier `images`), le
message complet (`news-franchise-AAAA-MM.eml`) et le paquet. Préparer à nouveau l'e-mail remplace l'export précédent du même mois.

## Installer le script (une seule fois)

1. Dans Google Drive, créez à la racine de **Mon Drive** un dossier nommé exactement
   **News Franchise** (ou changez `DOSSIER_DRIVE` en haut du script).
2. Ouvrez https://script.google.com, **Nouveau projet**, nommez-le « News Franchise ».
3. Remplacez le contenu de `Code.gs` par celui du fichier
   `apps_script/brouillon_gmail.gs` du projet, puis enregistrez.
4. Activez le service **Gmail API** : dans la colonne de gauche, **Services** (+), choisissez
   **Gmail API**, puis **Ajouter**. (Sans lui, le script s'arrête avec un message qui le
   rappelle.)
5. Choisissez la fonction **creerBrouillon** et cliquez **Exécuter**. Google demande
   d'autoriser le script à lire Google Drive et à gérer Gmail (création du brouillon) :
   acceptez. Cette autorisation n'est demandée qu'une fois.

**Mise à jour du script** : si le script répond « Format de paquet inattendu », recopiez
la dernière version de `apps_script/brouillon_gmail.gs` dans le projet Apps Script (et
vérifiez que le service Gmail API est bien ajouté).

### Pourquoi l'API Gmail plutôt que GmailApp ?

Les photos et logos sont des images **intégrées** au message (appelées par `cid:` dans le
HTML). Avec `GmailApp.createDraft(…, { inlineImages })`, ces images n'apparaissent pas
toujours dans un **brouillon** ouvert dans Gmail. L'application prépare donc elle-même le
message complet au format standard des e-mails (MIME : version texte, HTML, et chaque
image jointe « en ligne » avec son identifiant), et le script le dépose tel quel avec
l'API Gmail (`Gmail.Users.Drafts.create`). Le même message est enregistré dans
`news-franchise-AAAA-MM.eml`, que l'on peut ouvrir avec Outlook ou Thunderbird pour le
vérifier.

Si votre organisation Google Workspace bloque les scripts Apps Script ou les autorisations
demandées, l'administrateur doit les autoriser : le script ne peut pas s'en passer.

## Paquet : format

`news-franchise-AAAA-MM.json`, encodé en UTF-8 :

| Clé | Contenu |
| --- | --- |
| `format` | `news-franchise-email/3` (le script refuse un autre format) |
| `month`, `createdAt` | mois de la newsletter, date de préparation (UTC) |
| `raw` | message complet au format MIME, encodé en base64 « URL » (ce que dépose le script) ; texte et HTML y sont en UTF-8 lisible (« 8bit »), pour que le script y pose le lien du PDF |
| `printPdf` | `{fileName, mimeType, data}` : la version PDF à imprimer (`data` en base64), ou `null` |
| `printLinkToken` | adresse provisoire du lien « voir la version à imprimer », remplacé par le lien du PDF dans Drive, ou `null` |
| `subject` | objet : « News Franchise — Octobre 2026 » |
| `htmlBody` | HTML de l'e-mail ; les images y sont appelées par `cid:<nom>` |
| `textBody` | version texte |
| `images` | liste `{cid, fileName, mimeType, data}` (`data` en base64) |

## Limites connues

- Le PDF a été fabriqué et vérifié avec Chromium (le moteur d'Edge et de Chrome) pendant le
  développement, pas avec Edge sous Windows ; le partage Drive et le remplacement du lien ont
  été vérifiés en simulant les outils Google, pas dans un vrai compte : premier essai réel à
  faire sur le mois de démonstration.

- Le script n'a pas pu être exécuté pendant le développement (aucun accès à un compte
  Google depuis l'environnement de test). Le paquet, lui, est vérifié par les tests
  (format, images, liens) ; le premier essai réel est à faire sur le mois de
  démonstration (janvier 2000).
- Le rendu a été vérifié dans un navigateur, pas dans l'application Gmail elle-même :
  quelques détails (arrondis, polices) peuvent varier selon le lecteur de messagerie.
  Outlook (bureau) ignore les arrondis : les arches y deviennent des rectangles.
- Les polices de la charte ne s'affichent que si elles sont installées chez le lecteur
  (Century Gothic, Bahnschrift) ; sinon Arial prend le relais.
