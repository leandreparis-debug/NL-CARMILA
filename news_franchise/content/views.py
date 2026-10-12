"""Pages du contenu interne : ouvertures et photos, enseignes rencontrées, lien des plans.

Même socle que la relecture : POST puis redirection avec message, jeton CSRF, saisie
conservée en cas d'erreur (la page est réaffichée avec le message à côté du champ).
"""

from __future__ import annotations

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    url_for,
)
from flask.typing import ResponseReturnValue

from news_franchise.content import service
from news_franchise.db.connection import get_db
from news_franchise.models import Meeting, Newsletter, Opening, OpeningPhoto
from news_franchise.repositories import brands, meetings, openings
from news_franchise.review.service import FormError, moved_order
from news_franchise.review.views import (
    CardEdit,
    _limits,
    _newsletter,
    _render_month,
)

bp = Blueprint("content", __name__)

NEW_ITEM = 0  # identifiant fictif du formulaire d'ajout (pour réafficher sa saisie)
QUICK_ADD = -1  # identifiant fictif du formulaire d'ajout rapide


def _photos_dir() -> object:
    """Dossier des photos (<données>/photos)."""
    return current_app.config["NF_SETTINGS"].photos_dir


def _back(month: str, tab: str, anchor: str = "") -> ResponseReturnValue:
    """Redirection vers l'onglet et l'élément concerné."""
    target = url_for("review.month", month=month, tab=tab)
    return redirect(target + (f"#{anchor}" if anchor else ""))


def _refused(newsletter: Newsletter, tab: str, item_id: int, exc: FormError) -> ResponseReturnValue:
    """Réaffiche l'onglet avec la saisie refusée et le message à côté du champ fautif."""
    edit = CardEdit(item_id, request.form, {exc.field or "general": str(exc)})
    return _render_month(newsletter, tab, "tous", edit, 400)


def _opening(newsletter: Newsletter, opening_id: int) -> Opening:
    """Ouverture de cette newsletter ; 404 sinon."""
    opening = openings.get(get_db(), opening_id)
    if opening is None or opening.newsletter_id != newsletter.id:
        abort(404)
    return opening


def _photo(newsletter: Newsletter, photo_id: int) -> tuple[OpeningPhoto, Opening]:
    """Photo d'une ouverture de cette newsletter ; 404 sinon."""
    photo = openings.get_photo(get_db(), photo_id)
    if photo is None:
        abort(404)
    return photo, _opening(newsletter, photo.opening_id)


def _meeting(newsletter: Newsletter, meeting_id: int) -> Meeting:
    """Enseigne rencontrée de cette newsletter ; 404 sinon."""
    meeting = meetings.get(get_db(), meeting_id)
    if meeting is None or meeting.newsletter_id != newsletter.id:
        abort(404)
    return meeting


def _move(items: list[int], item_id: int) -> list[int] | None:
    """Nouvel ordre selon le déplacement demandé (sens, rang) ; None si rien ne change."""
    try:
        return moved_order(
            list(items), item_id, request.form.get("sens", ""), request.form.get("rang")
        )
    except FormError as exc:
        flash(str(exc), "error")
        return None


def _confirm(what: str, label: str, action: str, cancel: str, note: str) -> ResponseReturnValue:
    """Page de confirmation d'une suppression."""
    return render_template(
        "review/confirm_delete.html",
        what=what,
        label=label,
        action=action,
        cancel=cancel,
        note=note,
    )


# --------------------------------------------------------------------------- accès


@bp.get("/contenu-interne")
def start() -> ResponseReturnValue:
    """Bouton « Contenu interne » : ouvertures du mois en préparation (le plus récent au
    statut Brouillon), sinon la liste des newsletters."""
    draft = service.last_draft(get_db())
    if draft is None:
        flash("Aucune newsletter en préparation : ouvrez ou créez d'abord un mois.", "warning")
        return redirect(url_for("review.index"))
    return redirect(url_for("review.month", month=draft.month, tab="ouvertures"))


@bp.get("/photos/<path:file_name>")
def photo_file(file_name: str) -> ResponseReturnValue:
    """Sert une photo du dossier photos ; tout autre chemin (« .. », chemin absolu,
    autre type de fichier) donne 404."""
    if not file_name.endswith(".jpg") or "\\" in file_name or ".." in file_name:
        abort(404)
    return send_from_directory(_photos_dir(), file_name, mimetype="image/jpeg", max_age=3600)


# --------------------------------------------------------------------------- ouvertures


@bp.post("/newsletters/<month>/ouvertures/ajouter")
def add_opening(month: str) -> ResponseReturnValue:
    """Ajoute une ouverture (en fin de liste)."""
    newsletter = _newsletter(month)
    try:
        opening, warning = service.opening_from_form(
            request.form, newsletter, brands.list_all(get_db(), tracked_only=True)
        )
    except FormError as exc:
        return _refused(newsletter, "ouvertures", NEW_ITEM, exc)
    added = openings.add(get_db(), opening)
    flash(
        f"Ouverture ajoutée : {added.brand_name} — {added.location}. Ajoutez-lui des photos.",
        "success",
    )
    if warning:
        flash(warning, "warning")
    return _back(month, "ouvertures", f"ouverture-{added.id}")


@bp.post("/newsletters/<month>/ouvertures/<int:opening_id>")
def save_opening(month: str, opening_id: int) -> ResponseReturnValue:
    """Enregistre la modification d'une ouverture."""
    newsletter = _newsletter(month)
    current = _opening(newsletter, opening_id)
    try:
        opening, warning = service.opening_from_form(
            request.form, newsletter, brands.list_all(get_db(), tracked_only=True), current
        )
    except FormError as exc:
        return _refused(newsletter, "ouvertures", opening_id, exc)
    openings.update(get_db(), opening)
    flash("Ouverture enregistrée.", "success")
    if warning:
        flash(warning, "warning")
    return _back(month, "ouvertures", f"ouverture-{opening_id}")


@bp.post("/newsletters/<month>/ouvertures/<int:opening_id>/deplacer")
def move_opening(month: str, opening_id: int) -> ResponseReturnValue:
    """Déplace une ouverture (en tête, monter, descendre, en fin, rang)."""
    newsletter = _newsletter(month)
    _opening(newsletter, opening_id)
    ids = [o.id for o in openings.list_for_newsletter(get_db(), newsletter.id)]  # type: ignore[arg-type]
    order = _move(ids, opening_id)  # type: ignore[arg-type]
    if order is not None:
        openings.reorder(get_db(), newsletter.id, order)  # type: ignore[arg-type]
    return _back(month, "ouvertures", f"ouverture-{opening_id}")


@bp.route("/newsletters/<month>/ouvertures/<int:opening_id>/supprimer", methods=["GET", "POST"])
def delete_opening(month: str, opening_id: int) -> ResponseReturnValue:
    """Confirmation puis suppression d'une ouverture et de ses photos (fichiers compris)."""
    newsletter = _newsletter(month)
    opening = _opening(newsletter, opening_id)
    if request.method == "GET":
        return _confirm(
            "cette ouverture",
            f"{opening.brand_name} — {opening.location}",
            url_for("content.delete_opening", month=month, opening_id=opening_id),
            url_for("review.month", month=month, tab="ouvertures") + f"#ouverture-{opening_id}",
            "L'ouverture et toutes ses photos seront définitivement supprimées.",
        )
    openings.delete(get_db(), opening_id, _photos_dir())  # type: ignore[arg-type]
    flash(f"Ouverture supprimée : {opening.brand_name} — {opening.location}.", "success")
    return _back(month, "ouvertures")


# --------------------------------------------------------------------------- photos


@bp.post("/newsletters/<month>/ouvertures/<int:opening_id>/photos")
def upload_photos(month: str, opening_id: int) -> ResponseReturnValue:
    """Ajoute une ou plusieurs photos à une ouverture (dans la limite par ouverture)."""
    newsletter = _newsletter(month)
    opening = _opening(newsletter, opening_id)
    files = [(f.filename or "", f.read()) for f in request.files.getlist("photos")]
    result = service.add_photos(
        get_db(),
        opening,
        files,
        _photos_dir(),  # type: ignore[arg-type]
        newsletter.month,
        _limits().photos_par_ouverture,
    )
    if result.saved:
        count = len(result.saved)
        flash(
            f"{count} photo{'s' if count > 1 else ''} ajoutée{'s' if count > 1 else ''}.", "success"
        )
    for error in result.errors:
        flash(error, "error")
    return _back(month, "ouvertures", f"ouverture-{opening_id}")


@bp.post("/newsletters/<month>/photos/<int:photo_id>/legende")
def caption_photo(month: str, photo_id: int) -> ResponseReturnValue:
    """Enregistre la légende d'une photo."""
    newsletter = _newsletter(month)
    photo, opening = _photo(newsletter, photo_id)
    try:
        service.update_caption(get_db(), photo, request.form)
    except FormError as exc:
        flash(f"Légende non enregistrée : {exc}", "error")
    else:
        flash("Légende enregistrée.", "success")
    return _back(month, "ouvertures", f"ouverture-{opening.id}")


@bp.post("/newsletters/<month>/photos/<int:photo_id>/principale")
def main_photo(month: str, photo_id: int) -> ResponseReturnValue:
    """Choisit la photo principale de l'ouverture (placée en premier)."""
    newsletter = _newsletter(month)
    photo, opening = _photo(newsletter, photo_id)
    service.set_main_photo(get_db(), opening.id, photo_id)  # type: ignore[arg-type]
    flash("Photo principale choisie.", "success")
    return _back(month, "ouvertures", f"ouverture-{opening.id}")


@bp.route("/newsletters/<month>/photos/<int:photo_id>/supprimer", methods=["GET", "POST"])
def delete_photo(month: str, photo_id: int) -> ResponseReturnValue:
    """Confirmation puis suppression d'une photo (le fichier est supprimé du disque)."""
    newsletter = _newsletter(month)
    photo, opening = _photo(newsletter, photo_id)
    if request.method == "GET":
        return _confirm(
            "cette photo",
            f"Photo de l'ouverture {opening.brand_name} — {opening.location}",
            url_for("content.delete_photo", month=month, photo_id=photo_id),
            url_for("review.month", month=month, tab="ouvertures") + f"#ouverture-{opening.id}",
            "La photo sera définitivement supprimée.",
        )
    openings.delete_photo(get_db(), photo_id, _photos_dir())  # type: ignore[arg-type]
    flash("Photo supprimée.", "success")
    return _back(month, "ouvertures", f"ouverture-{opening.id}")


# --------------------------------------------------------------------------- enseignes rencontrées


@bp.post("/newsletters/<month>/rencontres/ajouter")
def add_meeting(month: str) -> ResponseReturnValue:
    """Ajoute une enseigne rencontrée (un doublon du mois est refusé)."""
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    try:
        meeting = service.meeting_from_form(request.form, newsletter.id)
        if service.is_duplicate_meeting(get_db(), newsletter.id, meeting.brand_name):
            raise FormError(
                f"« {meeting.brand_name} » est déjà dans la liste de ce mois.", "enseigne"
            )
    except FormError as exc:
        return _refused(newsletter, "rencontres", NEW_ITEM, exc)
    added = meetings.add(get_db(), meeting)
    flash(f"Enseigne rencontrée ajoutée : {added.brand_name}.", "success")
    return _back(month, "rencontres", f"rencontre-{added.id}")


@bp.post("/newsletters/<month>/rencontres/ajout-rapide")
def quick_add(month: str) -> ResponseReturnValue:
    """Ajout rapide : une enseigne par ligne, doublons ignorés et signalés."""
    newsletter = _newsletter(month)
    assert newsletter.id is not None
    try:
        result = service.quick_add_meetings(get_db(), newsletter.id, request.form.get("liste", ""))
    except FormError as exc:
        return _refused(newsletter, "rencontres", QUICK_ADD, exc)
    if result.added:
        flash(f"{len(result.added)} enseigne(s) ajoutée(s) : {', '.join(result.added)}.", "success")
    if result.ignored:
        flash(f"Déjà dans la liste, donc ignorée(s) : {', '.join(result.ignored)}.", "warning")
    return _back(month, "rencontres")


@bp.post("/newsletters/<month>/rencontres/<int:meeting_id>")
def save_meeting(month: str, meeting_id: int) -> ResponseReturnValue:
    """Enregistre la modification d'une enseigne rencontrée."""
    newsletter = _newsletter(month)
    current = _meeting(newsletter, meeting_id)
    assert newsletter.id is not None
    try:
        meeting = service.meeting_from_form(request.form, newsletter.id, current)
        if service.is_duplicate_meeting(get_db(), newsletter.id, meeting.brand_name, meeting_id):
            raise FormError(
                f"« {meeting.brand_name} » est déjà dans la liste de ce mois.", "enseigne"
            )
    except FormError as exc:
        return _refused(newsletter, "rencontres", meeting_id, exc)
    meetings.update(get_db(), meeting)
    flash("Enseigne rencontrée enregistrée.", "success")
    return _back(month, "rencontres", f"rencontre-{meeting_id}")


@bp.post("/newsletters/<month>/rencontres/<int:meeting_id>/deplacer")
def move_meeting(month: str, meeting_id: int) -> ResponseReturnValue:
    """Déplace une enseigne rencontrée."""
    newsletter = _newsletter(month)
    _meeting(newsletter, meeting_id)
    ids = [m.id for m in meetings.list_for_newsletter(get_db(), newsletter.id)]  # type: ignore[arg-type]
    order = _move(ids, meeting_id)  # type: ignore[arg-type]
    if order is not None:
        meetings.reorder(get_db(), newsletter.id, order)  # type: ignore[arg-type]
    return _back(month, "rencontres", f"rencontre-{meeting_id}")


@bp.route("/newsletters/<month>/rencontres/<int:meeting_id>/supprimer", methods=["GET", "POST"])
def delete_meeting(month: str, meeting_id: int) -> ResponseReturnValue:
    """Confirmation puis suppression d'une enseigne rencontrée."""
    newsletter = _newsletter(month)
    meeting = _meeting(newsletter, meeting_id)
    if request.method == "GET":
        return _confirm(
            "cette enseigne rencontrée",
            meeting.brand_name,
            url_for("content.delete_meeting", month=month, meeting_id=meeting_id),
            url_for("review.month", month=month, tab="rencontres") + f"#rencontre-{meeting_id}",
            "Elle sera retirée de la rubrique 4 de ce mois.",
        )
    meetings.delete(get_db(), meeting_id)
    flash(f"Enseigne rencontrée supprimée : {meeting.brand_name}.", "success")
    return _back(month, "rencontres")


# --------------------------------------------------------------------------- plans


@bp.post("/newsletters/<month>/plans/enregistrer")
def save_plans(month: str) -> ResponseReturnValue:
    """Enregistre le lien des plans de développement (format vérifié, lien jamais appelé)."""
    newsletter = _newsletter(month)
    try:
        service.save_plans_link(get_db(), newsletter, request.form)
    except FormError as exc:
        return _refused(newsletter, "plans", NEW_ITEM, exc)
    flash(
        "Lien des plans de développement enregistré. Testez-le avec « Ouvrir le lien ».", "success"
    )
    return _back(month, "plans")


@bp.post("/newsletters/<month>/plans/retirer")
def clear_plans(month: str) -> ResponseReturnValue:
    """Retire le lien des plans de développement."""
    newsletter = _newsletter(month)
    service.clear_plans_link(get_db(), newsletter)
    flash("Lien des plans de développement retiré.", "success")
    return _back(month, "plans")
