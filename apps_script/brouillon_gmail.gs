/**
 * News Franchise — crée le brouillon Gmail de la newsletter.
 *
 * Lit, dans le dossier Google Drive DOSSIER_DRIVE, le paquet le plus récent produit par
 * l'application (news-franchise-AAAA-MM.json), puis crée un brouillon dans Gmail avec le
 * message complet préparé par l'application (texte, HTML et images intégrées). Aucun
 * destinataire n'est ajouté : vous les choisissez dans Gmail avant l'envoi. Rien n'est
 * envoyé par ce script.
 *
 * Le brouillon est créé avec l'API Gmail (service avancé « Gmail API », à ajouter une fois
 * dans l'éditeur : Services +) : c'est ce qui garde les photos et logos visibles dans le
 * brouillon (avec GmailApp.createDraft et inlineImages, elles n'y apparaissent pas toujours).
 *
 * Installation : voir docs/email.md dans le projet News Franchise.
 */

/** Nom du dossier Google Drive où déposer les paquets (à la racine de « Mon Drive »). */
const DOSSIER_DRIVE = 'News Franchise';

/** Format de paquet attendu (produit par l'application). */
const FORMAT_PAQUET = 'news-franchise-email/2';

/** Noms de paquets reconnus : news-franchise-AAAA-MM.json */
const MOTIF_NOM = /^news-franchise-\d{4}-(0[1-9]|1[0-2])\.json$/;

/**
 * Crée le brouillon à partir du paquet le plus récent du dossier.
 * Fonction à lancer depuis l'éditeur Apps Script (bouton « Exécuter »).
 */
function creerBrouillon() {
  if (typeof Gmail === 'undefined') {
    throw new Error('Service « Gmail API » non activé. Dans l\'éditeur Apps Script, ' +
      'cliquez sur « Services » (+) à gauche, choisissez « Gmail API », puis « Ajouter ». ' +
      'Relancez ensuite creerBrouillon.');
  }
  const fichier = dernierPaquet_();
  const paquet = lirePaquet_(fichier);
  const brouillon = Gmail.Users.Drafts.create({ message: { raw: paquet.raw } }, 'me');
  Logger.log(
    'Brouillon créé : « %s » (%s images), depuis %s. Ouvrez Gmail > Brouillons, ' +
      'ajoutez les destinataires, relisez, puis envoyez.',
    paquet.subject,
    paquet.images.length,
    fichier.getName()
  );
  return brouillon.id;
}

/** Paquet le plus récent (date de modification) du dossier DOSSIER_DRIVE. */
function dernierPaquet_() {
  const dossiers = DriveApp.getFoldersByName(DOSSIER_DRIVE);
  if (!dossiers.hasNext()) {
    throw new Error('Dossier Google Drive introuvable : « ' + DOSSIER_DRIVE + ' ». ' +
      'Créez-le à la racine de Mon Drive, ou changez DOSSIER_DRIVE en haut du script.');
  }
  const fichiers = dossiers.next().getFiles();
  let dernier = null;
  while (fichiers.hasNext()) {
    const fichier = fichiers.next();
    if (MOTIF_NOM.test(fichier.getName()) &&
        (dernier === null || fichier.getLastUpdated() > dernier.getLastUpdated())) {
      dernier = fichier;
    }
  }
  if (dernier === null) {
    throw new Error('Aucun paquet news-franchise-AAAA-MM.json dans le dossier « ' +
      DOSSIER_DRIVE + ' ». Préparez l\'e-mail dans l\'application, puis déposez le paquet.');
  }
  return dernier;
}

/** Lit et vérifie un paquet. */
function lirePaquet_(fichier) {
  let paquet;
  try {
    paquet = JSON.parse(fichier.getBlob().getDataAsString('UTF-8'));
  } catch (erreur) {
    throw new Error('Paquet illisible : ' + fichier.getName() + ' (' + erreur + ').');
  }
  if (paquet.format !== FORMAT_PAQUET) {
    throw new Error('Format de paquet inattendu (' + paquet.format + ', attendu ' +
      FORMAT_PAQUET + ') : copiez la dernière version de apps_script/brouillon_gmail.gs ' +
      'dans ce projet, ou préparez à nouveau l\'e-mail dans l\'application.');
  }
  ['raw', 'subject', 'htmlBody', 'textBody'].forEach(function (cle) {
    if (typeof paquet[cle] !== 'string' || paquet[cle] === '') {
      throw new Error('Paquet incomplet : « ' + cle + ' » manquant.');
    }
  });
  if (!Array.isArray(paquet.images)) {
    throw new Error('Paquet incomplet : « images » manquant.');
  }
  return paquet;
}
