"""Tests de l'interface de relecture (étape 6)."""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from flask import Flask
from flask.testing import FlaskClient

from news_franchise.config import Settings
from news_franchise.http_client import Fetcher
from news_franchise.models import Article, Franchisee, Newsletter
from news_franchise.repositories import articles, brands, franchisees, newsletters
from news_franchise.review.limits import DEFAULT_LIMITS, load_limits
from news_franchise.security import secret_key_path
from news_franchise.tools import demo
from tests.helpers import post_form, serve

NOW = datetime(2026, 11, 3, 9, 0, tzinfo=UTC)
BASE = "/newsletters/2026-10"


@pytest.fixture
def review_app(app: Flask, tmp_path: Path) -> Flask:
    app.config.update(
        NF_CLOCK=lambda: NOW,
        NF_FETCHER_FACTORY=lambda: Fetcher(sleep=lambda _: None),
        NF_LIMITS_FILE=tmp_path / "limites-absent.yaml",
    )
    return app


@pytest.fixture
def web(review_app: Flask) -> FlaskClient:
    return review_app.test_client()


def _add(
    conn: sqlite3.Connection, newsletter: Newsletter, index: int, rubric: int = 1, **kwargs: object
) -> Article:
    assert newsletter.id is not None
    added = articles.add(
        conn,
        Article(
            newsletter_id=newsletter.id,
            rubric=rubric,
            title=kwargs.pop("title", f"Article {index}"),  # type: ignore[arg-type]
            source_name="Toute la Franchise",
            url=f"https://site.example/articles/{index}",
            excerpt="Premières lignes d'origine.",
            published_at=datetime(2026, 10, 5, 8, 30, tzinfo=UTC),
            **kwargs,  # type: ignore[arg-type]
        ),
    )
    assert added is not None
    return added


def _html(response: object) -> str:
    return response.get_data(as_text=True)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- liste


def test_list_and_create_month(web: FlaskClient, conn: sqlite3.Connection) -> None:
    newsletters.get_or_create(conn, "2026-09")
    reviewed = newsletters.get_or_create(conn, "2026-08")
    newsletters.set_status(conn, reviewed.id, "reviewed")  # type: ignore[arg-type]

    html = _html(web.get("/newsletters/"))
    assert html.index("Septembre 2026") < html.index("Août 2026")
    assert "Brouillon" in html and "Relue" in html
    assert 'value="2026-10"' in html  # mois précédent proposé

    response = post_form(web, "/newsletters/", {"mois": "2026-10"})
    assert response.status_code == 302
    assert response.headers["Location"].endswith(f"{BASE}/rubrique-1")
    assert newsletters.get(conn, "2026-10") is not None
    assert "Newsletter de Octobre 2026 créée." in _html(web.get(f"{BASE}/rubrique-1"))
    assert post_form(web, "/newsletters/", {"mois": "2026-13"}).status_code == 302
    assert "Format attendu" in _html(web.get("/newsletters/"))


def test_home_review_button(web: FlaskClient) -> None:
    assert 'href="/newsletters/"' in _html(web.get("/"))


# --------------------------------------------------------------------------- articles


def test_retain_counter_and_limit_warning(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    items = [_add(conn, newsletter, i) for i in range(7)]
    html = _html(web.get(f"{BASE}/rubrique-1"))
    assert "<strong>7 retenus</strong> / limite 6" in html
    assert "counter-over" in html and "limite dépassée" in html
    assert "4 pages A4" in html

    post_form(web, f"{BASE}/articles/{items[0].id}/retenir", {"valeur": "0"})
    assert articles.get(conn, items[0].id).selected is False  # type: ignore[union-attr, arg-type]
    html = _html(web.get(f"{BASE}/rubrique-1"))
    assert "<strong>6 retenus</strong> / limite 6" in html
    assert "counter-over" not in html
    assert "Article retiré de la newsletter." in html

    retained = _html(web.get(f"{BASE}/rubrique-1?filtre=non-retenus"))
    assert "Article 0" in retained and "Article 1" not in retained


def test_save_card_ignores_forged_url(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    pokawa = brands.get_by_name(conn, "Pokawa")
    assert pokawa is not None
    response = post_form(
        web,
        f"{BASE}/articles/{article.id}",
        {
            "retenir": "on",
            "titre": "Titre corrigé",
            "extrait": "Premières lignes coupées.",
            "source": "Toute la Franchise",
            "enseigne": str(pokawa.id),
            "secteur": "",
            "date": "2026-10-05",
            "url": "https://pirate.example/faux",
            "lien": "https://pirate.example/faux",
        },
    )
    assert response.status_code == 302
    saved = articles.get(conn, article.id)  # type: ignore[arg-type]
    assert saved is not None
    assert saved.title == "Titre corrigé" and saved.excerpt == "Premières lignes coupées."
    assert saved.url == "https://site.example/articles/1"
    assert saved.brand_id == pokawa.id and saved.sector == pokawa.sector
    assert saved.published_at == article.published_at  # même jour : heure d'origine gardée


def test_other_brand_and_validation_errors(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    form = {
        "titre": "Titre",
        "source": "Source",
        "enseigne": "autre",
        "enseigne_autre": "Burger King",
    }
    post_form(web, f"{BASE}/articles/{article.id}", form)
    saved = articles.get(conn, article.id)  # type: ignore[arg-type]
    assert saved is not None and saved.brand_label == "Burger King" and saved.brand_id is None

    for bad, field, message in [
        ({**form, "titre": ""}, "titre", "« Titre » est obligatoire"),
        ({**form, "titre": "x" * 301}, "titre", "trop long"),
        ({**form, "date": "2026-02-30"}, "date", "pas une date valide"),
        ({**form, "enseigne_autre": ""}, "autre", "Autre enseigne"),
    ]:
        response = post_form(web, f"{BASE}/articles/{article.id}", bad)
        html = _html(response)
        assert response.status_code == 400
        assert re.search(
            rf'id="a{article.id}-{field}-err" role="alert">[^<]*{re.escape(message)}', html
        ), field
    unchanged = articles.get(conn, article.id)  # type: ignore[arg-type]
    assert unchanged is not None and unchanged.title == "Titre"


def test_refused_card_keeps_every_typed_value(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    pokawa = brands.get_by_name(conn, "Pokawa")
    assert pokawa is not None
    response = post_form(
        web,
        f"{BASE}/articles/{article.id}",
        {
            "titre": "",
            "source": "Source corrigée",
            "secteur": "Snacking sain",
            "date": "2026-10-07",
            "extrait": "Mon extrait raccourci <b>sans balise</b>.",
            "enseigne": str(pokawa.id),
            "opportunite": "on",
        },
    )
    html = _html(response)
    assert response.status_code == 400
    card = html[html.index(f'id="article-{article.id}"') :]
    assert 'value="Source corrigée"' in card and 'value="Snacking sain"' in card
    assert 'value="2026-10-07"' in card
    assert "Mon extrait raccourci &lt;b&gt;sans balise&lt;/b&gt;." in card
    assert f'<option value="{pokawa.id}" selected>' in card
    assert 'name="opportunite" checked' in card
    assert 'value=""' in card.split(f'id="a{article.id}-titre"')[1][:80]
    assert "« Titre » est obligatoire" in card
    assert '<details class="card-details" open>' in card
    assert '<span class="badge badge-unsaved" >Modifications non enregistrées' in card
    assert articles.get(conn, article.id).source_name == "Toute la Franchise"  # type: ignore[union-attr, arg-type]


def test_card_form_has_no_retain_checkbox(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    html = _html(web.get(f"{BASE}/rubrique-1"))
    assert 'name="retenir"' not in html
    assert "✓ Retenu — ne plus retenir" in html
    # Envoyer « retenir » au formulaire de carte ne change rien : seul le bouton rapide compte.
    articles.set_selected(conn, article.id, False)  # type: ignore[arg-type]
    post_form(web, f"{BASE}/articles/{article.id}", {"titre": "T", "source": "S", "retenir": "on"})
    assert articles.get(conn, article.id).selected is False  # type: ignore[union-attr, arg-type]
    post_form(web, f"{BASE}/articles/{article.id}/retenir", {"valeur": "1"})
    assert articles.get(conn, article.id).selected is True  # type: ignore[union-attr, arg-type]


def test_compact_view_and_unfold_all(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    _add(conn, newsletter, 1)
    html = _html(web.get(f"{BASE}/rubrique-1"))
    assert '<details class="card-details" >' in html and "<summary>Modifier</summary>" in html
    assert "Tout déplier" in html
    unfolded = _html(web.get(f"{BASE}/rubrique-1?deplier=1"))
    assert '<details class="card-details" open>' in unfolded and "Tout replier" in unfolded


def _order(conn: sqlite3.Connection, newsletter: Newsletter, rubric: int = 1) -> list[str]:
    return [a.title for a in articles.list_for_rubric(conn, newsletter.id, rubric)]  # type: ignore[arg-type]


def test_move_and_keep_first(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    items = [_add(conn, newsletter, i) for i in range(8)]
    post_form(web, f"{BASE}/articles/{items[2].id}/deplacer", {"sens": "haut"})
    post_form(web, f"{BASE}/articles/{items[0].id}/deplacer", {"sens": "bas"})
    order = [a.id for a in articles.list_for_rubric(conn, newsletter.id, 1)]  # type: ignore[arg-type]
    assert order[:3] == [items[2].id, items[0].id, items[1].id]

    response = post_form(web, f"{BASE}/rubrique-1/garder-premiers", {})
    assert response.status_code == 302
    listed = articles.list_for_rubric(conn, newsletter.id, 1)  # type: ignore[arg-type]
    assert [a.selected for a in listed] == [True] * 6 + [False] * 2
    assert "Seuls les 6 premiers articles sont retenus." in _html(web.get(f"{BASE}/rubrique-1"))


def test_place_first_last_and_rank(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    items = [_add(conn, newsletter, i) for i in range(5)]
    post_form(web, f"{BASE}/articles/{items[4].id}/deplacer", {"sens": "tete"})
    assert _order(conn, newsletter) == [
        "Article 4",
        "Article 0",
        "Article 1",
        "Article 2",
        "Article 3",
    ]
    post_form(web, f"{BASE}/articles/{items[4].id}/deplacer", {"sens": "fin"})
    assert _order(conn, newsletter)[-1] == "Article 4"
    post_form(web, f"{BASE}/articles/{items[4].id}/deplacer", {"sens": "rang", "rang": "2"})
    assert _order(conn, newsletter)[1] == "Article 4"
    post_form(web, f"{BASE}/articles/{items[0].id}/deplacer", {"sens": "rang", "rang": "99"})
    assert _order(conn, newsletter)[-1] == "Article 0"  # borné à la dernière place
    post_form(web, f"{BASE}/articles/{items[0].id}/deplacer", {"sens": "rang", "rang": "-4"})
    assert _order(conn, newsletter)[0] == "Article 0"  # borné à la première place
    before = _order(conn, newsletter)
    post_form(web, f"{BASE}/articles/{items[1].id}/deplacer", {"sens": "rang", "rang": "trois"})
    assert _order(conn, newsletter) == before
    assert "Le rang doit être un numéro" in _html(web.get(f"{BASE}/rubrique-1"))


def test_change_rubric(web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    moving = _add(conn, newsletter, 1, title="Article à reclasser")
    _add(conn, newsletter, 2, rubric=2, title="Déjà en rubrique 2")
    response = post_form(
        web, f"{BASE}/articles/{moving.id}/rubrique", {"cible": "2", "enseigne": ""}
    )
    assert response.status_code == 302
    assert articles.get(conn, moving.id).rubric == 1  # type: ignore[union-attr, arg-type]
    assert "Choisissez l&#39;enseigne" in _html(web.get(f"{BASE}/rubrique-1"))

    wycon = brands.get_by_name(conn, "Wycon")
    assert wycon is not None
    post_form(
        web, f"{BASE}/articles/{moving.id}/rubrique", {"cible": "2", "enseigne": str(wycon.id)}
    )
    moved = articles.get(conn, moving.id)  # type: ignore[arg-type]
    assert moved is not None and moved.rubric == 2 and moved.brand_id == wycon.id
    assert moved.sector == wycon.sector
    assert _order(conn, newsletter, 2) == ["Déjà en rubrique 2", "Article à reclasser"]
    assert "Article déplacé en fin de Rubrique 2" in _html(web.get(f"{BASE}/rubrique-1"))

    post_form(web, f"{BASE}/articles/{moving.id}/rubrique", {"cible": "1"})
    back = articles.get(conn, moving.id)  # type: ignore[arg-type]
    assert back is not None and back.rubric == 1 and back.url == moving.url
    assert back.title == "Article à reclasser" and back.selected and back.brand_id == wycon.id

    post_form(
        web,
        f"{BASE}/articles/{moving.id}/rubrique",
        {"cible": "2", "enseigne": "autre", "enseigne_autre": "Burger King"},
    )
    other = articles.get(conn, moving.id)  # type: ignore[arg-type]
    assert other is not None and other.rubric == 2 and other.brand_label == "Burger King"


def test_remove_detected_opportunity_becomes_manual(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    articles.apply_auto_opportunity(
        conn,
        article.id,
        True,
        "Pokawa recherche des emplacements en centre commercial.",
        ["x"],  # type: ignore[arg-type]
    )
    html = _html(web.get(f"{BASE}/rubrique-1?filtre=opportunites"))
    assert "Repère détecté automatiquement" in html and "Article 1" in html

    post_form(
        web,
        f"{BASE}/articles/{article.id}",
        {"titre": "Article 1", "source": "Source", "retenir": "on"},
    )
    saved = articles.get(conn, article.id)  # type: ignore[arg-type]
    assert saved is not None and saved.is_opportunity is False
    assert saved.opportunity_source == "manual"


def test_delete_article_with_confirmation(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    page = _html(web.get(f"{BASE}/articles/{article.id}/supprimer"))
    assert "Supprimer cet article ?" in page and "Oui, supprimer" in page
    assert articles.get(conn, article.id) is not None  # type: ignore[arg-type]
    post_form(web, f"{BASE}/articles/{article.id}/supprimer", {})
    assert articles.get(conn, article.id) is None  # type: ignore[arg-type]


def test_article_of_another_month_is_404(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    other = _add(conn, newsletters.get_or_create(conn, "2026-09"), 9)
    response = post_form(web, f"{BASE}/articles/{other.id}/retenir", {"valeur": "0"})
    assert response.status_code == 404


# --------------------------------------------------------------------------- ajout manuel

PAGE = """<!doctype html><html><head><title>Titre HTML</title>
<meta property="og:title" content="Une enseigne recrute ses franchisés">
<meta property="og:site_name" content="Le Journal Exemple">
<meta property="article:published_time" content="2026-10-12T08:00:00+02:00"></head>
<body><nav class="menu"><p>Menu du site avec beaucoup de liens inutiles ici.</p></nav>
<article><p>La jeune enseigne annonce le recrutement de ses premiers franchisés
en Bretagne cette année.</p></article>
</body></html>"""


def test_manual_article_added_after_link_check(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter, mock_http: respx.MockRouter
) -> None:
    link = "https://journal.example/actu/enseigne?utm_source=mail"
    serve(mock_http, {"https://journal.example/actu/enseigne": httpx.Response(200, text=PAGE)})

    step2 = post_form(web, f"{BASE}/ajouter-article/verifier", {"lien": link, "rubrique": "1"})
    html = _html(step2)
    assert step2.status_code == 200
    assert 'value="Une enseigne recrute ses franchisés"' in html
    assert 'value="Le Journal Exemple"' in html and 'value="2026-10-12"' in html
    assert "La jeune enseigne annonce" in html
    assert articles.list_for_newsletter(conn, newsletter.id) == []  # type: ignore[arg-type]

    response = post_form(
        web,
        f"{BASE}/ajouter-article/enregistrer",
        {
            "lien": "https://journal.example/actu/enseigne",
            "rubrique": "1",
            "titre": "Une enseigne recrute ses franchisés",
            "source": "Le Journal Exemple",
            "extrait": "La jeune enseigne annonce le recrutement de ses premiers franchisés.",
            "date": "2026-10-12",
        },
    )
    assert response.status_code == 302
    [added] = articles.list_for_newsletter(conn, newsletter.id)  # type: ignore[arg-type]
    assert added.url == "https://journal.example/actu/enseigne"
    assert added.title == "Une enseigne recrute ses franchisés" and added.selected
    assert added.body_text is not None and "Bretagne" in added.body_text

    again = post_form(web, f"{BASE}/ajouter-article/verifier", {"lien": link, "rubrique": "1"})
    assert again.status_code == 400 and "déjà dans la newsletter" in _html(again)


@pytest.mark.parametrize(
    ("link", "message"),
    [
        ("https://journal.example/disparu", "Page introuvable (HTTP 404)"),
        ("ftp://journal.example/fichier", "http:// ou https://"),
        ("", "obligatoire"),
    ],
)
def test_manual_article_refused(
    web: FlaskClient,
    conn: sqlite3.Connection,
    newsletter: Newsletter,
    mock_http: respx.MockRouter,
    link: str,
    message: str,
) -> None:
    serve(mock_http, {})
    response = post_form(web, f"{BASE}/ajouter-article/verifier", {"lien": link, "rubrique": "2"})
    assert response.status_code == 400
    assert message in _html(response)
    forged = post_form(
        web, f"{BASE}/ajouter-article/enregistrer", {"lien": link, "titre": "T", "source": "S"}
    )
    assert forged.status_code == 400
    assert articles.list_for_newsletter(conn, newsletter.id) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------- franchisés


def _detected(conn: sqlite3.Connection, newsletter: Newsletter, name: str) -> Franchisee:
    assert newsletter.id is not None
    return franchisees.add(
        conn,
        Franchisee(
            newsletter_id=newsletter.id,
            name=name,
            brands="O'Tacos",
            source_name="Toute la Franchise",
            source_url="https://site.example/articles/source",
            confidence="moyenne",
            evidence=f"{name}, multi-franchisé O'Tacos.",
        ),
    )


def test_franchisee_validate_edit_delete(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    first = _detected(conn, newsletter, "Jean Dupont")
    second = _detected(conn, newsletter, "Anne Petit")
    html = _html(web.get(f"{BASE}/franchises"))
    assert "Extrait qui justifie la détection" in html
    assert "Jean Dupont, multi-franchisé O&#39;Tacos." in html and "Fiche partielle" in html
    assert "pas la fiabilité de la détection" in html
    assert "<strong>0 validés</strong> / limite 5" in html

    post_form(web, f"{BASE}/franchises/{first.id}/valider", {"valeur": "1"})
    assert franchisees.get(conn, first.id).validated  # type: ignore[union-attr, arg-type]

    post_form(
        web,
        f"{BASE}/franchises/{first.id}",
        {
            "nom": "Jean Dupont",
            "enseignes": "O'Tacos",
            "lieu": "Toulouse",
            "nombre": "",
            "valider": "on",
            "source_url": "https://pirate.example",
        },
    )
    saved = franchisees.get(conn, first.id)  # type: ignore[arg-type]
    assert saved is not None and saved.edited and saved.location == "Toulouse"
    assert saved.store_count is None and saved.source_url == "https://site.example/articles/source"
    refused = post_form(
        web, f"{BASE}/franchises/{first.id}", {"nom": "Jean Dupont", "lieu": "Albi", "nombre": "-3"}
    )
    html = _html(refused)
    assert refused.status_code == 400
    assert f'id="f{first.id}-nombre-err" role="alert">' in html and "nombre entier positif" in html
    assert 'value="Albi"' in html and 'value="-3"' in html

    post_form(web, f"{BASE}/franchises/{second.id}/deplacer", {"sens": "haut"})
    assert [f.id for f in franchisees.list_for_newsletter(conn, newsletter.id)] == [
        second.id,
        first.id,
    ]  # type: ignore[arg-type]

    post_form(web, f"{BASE}/franchises/{second.id}/supprimer", {})
    removed = franchisees.get(conn, second.id)  # type: ignore[arg-type]
    assert removed is not None and removed.dismissed  # suggestion écartée, jamais recréée
    assert f'id="franchise-{second.id}"' not in _html(web.get(f"{BASE}/franchises"))


def test_manual_franchisee_requires_checked_source(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter, mock_http: respx.MockRouter
) -> None:
    serve(mock_http, {"https://journal.example/portrait": httpx.Response(200, text=PAGE)})
    missing = post_form(web, f"{BASE}/ajouter-franchise", {"nom": "Paul Martin"})
    assert missing.status_code == 400 and "Lien" in _html(missing)
    broken = post_form(
        web,
        f"{BASE}/ajouter-franchise",
        {"nom": "Paul Martin", "lien_source": "https://journal.example/absent"},
    )
    assert broken.status_code == 400 and "HTTP 404" in _html(broken)
    assert franchisees.list_for_newsletter(conn, newsletter.id) == []  # type: ignore[arg-type]

    ok = post_form(
        web,
        f"{BASE}/ajouter-franchise",
        {
            "nom": "Paul Martin",
            "enseignes": "Wycon",
            "nombre": "3",
            "valider": "on",
            "lien_source": "https://journal.example/portrait",
        },
    )
    assert ok.status_code == 302
    [fiche] = franchisees.list_for_newsletter(conn, newsletter.id)  # type: ignore[arg-type]
    assert fiche.source_url == "https://journal.example/portrait"
    assert fiche.source_name == "Le Journal Exemple"
    assert fiche.validated and fiche.confidence is None and fiche.store_count == 3

    post_form(web, f"{BASE}/franchises/{fiche.id}/supprimer", {})
    assert franchisees.get(conn, fiche.id) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- statut


def test_mark_reviewed_and_back_to_draft(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    for i in range(7):
        _add(conn, newsletter, i)
    post_form(web, f"{BASE}/statut", {"statut": "relue", "onglet": "rubrique-1"})
    assert newsletters.get(conn, "2026-10").status == "reviewed"  # type: ignore[union-attr]
    html = _html(web.get(f"{BASE}/rubrique-1"))
    assert "marquée comme relue" in html
    assert "7 articles retenus pour une limite de 6" in html
    assert "Aucun franchisé n&#39;est validé" in html
    assert "Repasser en brouillon" in html

    post_form(web, f"{BASE}/statut", {"statut": "brouillon"})
    assert newsletters.get(conn, "2026-10").status == "draft"  # type: ignore[union-attr]


# --------------------------------------------------------------------------- sécurité


def test_post_without_csrf_token_is_rejected(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    response = web.post(f"{BASE}/articles/{article.id}/retenir", data={"valeur": "0"})
    assert response.status_code == 400
    assert "Formulaire expiré" in _html(response)
    assert articles.get(conn, article.id).selected  # type: ignore[union-attr, arg-type]
    bad_token = web.post(
        f"{BASE}/articles/{article.id}/retenir", data={"valeur": "0", "csrf_token": "faux"}
    )
    assert bad_token.status_code == 400


def test_foreign_host_is_rejected(web: FlaskClient) -> None:
    for host in ("evil.example", "evil.example:5000", "127.0.0.1:6000", "127.0.0.1"):
        response = web.get("/newsletters/", headers={"Host": host})
        assert response.status_code == 400, host
        assert "Adresse non autorisée" in _html(response)
    assert web.get("/newsletters/", headers={"Host": "localhost:5000"}).status_code == 200
    assert web.get("/newsletters/", headers={"Host": "127.0.0.1:5000"}).status_code == 200


def test_site_content_is_escaped(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    _add(conn, newsletter, 1, title="<script>alert('x')</script> Titre piégé")
    html = _html(web.get(f"{BASE}/rubrique-1"))
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt; Titre piégé" in html


def test_secret_key_is_created_once(settings: Settings, review_app: Flask) -> None:
    key_file = secret_key_path(settings)
    assert key_file.is_file()
    key = key_file.read_text(encoding="ascii")
    assert len(key) == 64 and review_app.config["SECRET_KEY"] == key
    from tests.helpers import web_app

    assert web_app(settings).config["SECRET_KEY"] == key


# --------------------------------------------------------------------------- limites


def test_limits_file(tmp_path: Path) -> None:
    assert load_limits(tmp_path / "absent.yaml") == (DEFAULT_LIMITS, None)
    assert DEFAULT_LIMITS.rubrique_1 == 6 and DEFAULT_LIMITS.rubrique_2 == 8
    assert DEFAULT_LIMITS.franchises == 5 and DEFAULT_LIMITS.ouvertures == 4
    path = tmp_path / "limites.yaml"
    path.write_text("rubrique_1: 3\n", encoding="utf-8")
    limits, error = load_limits(path)
    assert error is None and limits.rubrique_1 == 3 and limits.rubrique_2 == 8
    for text, message in [
        ("rubrique_1: beaucoup\n", "nombre entier"),
        ("rubrique_1: 0\n", "entre 1 et 100"),
        ("rubric_1: 3\n", "clé(s) inconnue(s) rubric_1"),
        ("rubrique_1: [\n", "illisible"),
    ]:
        path.write_text(text, encoding="utf-8")
        limits, error = load_limits(path)
        assert limits == DEFAULT_LIMITS and error is not None and message in error


def test_invalid_limits_message_in_page(
    review_app: Flask, web: FlaskClient, newsletter: Newsletter, tmp_path: Path
) -> None:
    bad = tmp_path / "limites.yaml"
    bad.write_text("rubrique_2: -1\n", encoding="utf-8")
    review_app.config["NF_LIMITS_FILE"] = bad
    html = _html(web.get(f"{BASE}/rubrique-2"))
    assert "« rubrique_2 » doit être un nombre entier" in html
    assert "/ limite 8" in html


def test_project_limits_file_is_valid() -> None:
    limits, error = load_limits()
    assert error is None and limits == DEFAULT_LIMITS


# --------------------------------------------------------------------------- démonstration


def test_demo_dataset(settings: Settings, conn: sqlite3.Connection, web: FlaskClient) -> None:
    brands.sync_from_yaml(conn)
    output: list[str] = []
    assert demo.main([], settings=settings, out=output.append) == 0
    assert demo.main([], settings=settings, out=output.append) == 2  # déjà présente
    assert demo.main(["--reset"], settings=settings, out=output.append) == 0
    assert [n.month for n in newsletters.list_all(conn)] == ["2000-01"]
    demo_articles = articles.list_for_newsletter(conn, newsletters.get(conn, "2000-01").id)  # type: ignore[union-attr, arg-type]
    assert all(a.title.startswith("[DÉMO]") for a in demo_articles)
    assert all(a.url.startswith("https://example.com/demo/") for a in demo_articles)
    assert any(a.is_opportunity for a in demo_articles)
    html = _html(web.get("/newsletters/2000-01/rubrique-1"))
    assert "&lt;script&gt;" in html and "<script>alert" not in html
    assert "Jean Exemple" in _html(web.get("/newsletters/2000-01/franchises"))


# --------------------------------------------------------------------------- étape 6 bis

ROBOTS_DENY_ALL = httpx.Response(200, text="User-agent: *\nDisallow: /\n")


def test_manual_add_ignores_robots_txt(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter, mock_http: respx.MockRouter
) -> None:
    routes = serve(
        mock_http,
        {
            "https://journal.example/robots.txt": ROBOTS_DENY_ALL,
            "https://journal.example/actu/ferme": httpx.Response(200, text=PAGE),
        },
    )
    step2 = post_form(
        web,
        f"{BASE}/ajouter-article/verifier",
        {"lien": "https://journal.example/actu/ferme", "rubrique": "1"},
    )
    assert step2.status_code == 200
    assert 'value="Une enseigne recrute ses franchisés"' in _html(step2)
    assert routes["https://journal.example/robots.txt"].call_count == 0
    saved = post_form(
        web,
        f"{BASE}/ajouter-article/enregistrer",
        {
            "lien": "https://journal.example/actu/ferme",
            "rubrique": "1",
            "titre": "Une enseigne recrute",
            "source": "Le Journal Exemple",
        },
    )
    assert saved.status_code == 302
    [added] = articles.list_for_newsletter(conn, newsletter.id)  # type: ignore[arg-type]
    assert added.link_verified_by_user is False


def test_manual_add_site_refusing_robots_needs_confirmation(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter, mock_http: respx.MockRouter
) -> None:
    link = "https://protege.example/article-42"
    serve(mock_http, {link: httpx.Response(403, text="Accès refusé aux robots")})

    step2 = post_form(web, f"{BASE}/ajouter-article/verifier", {"lien": link, "rubrique": "2"})
    html = _html(step2)
    assert step2.status_code == 200
    assert "Le site refuse la lecture automatique" in html
    assert "J'ai ouvert ce lien dans mon navigateur et il affiche bien l'article" in html
    assert 'name="confirme"' in html

    pokawa = brands.get_by_name(conn, "Pokawa")
    assert pokawa is not None
    form = {
        "lien": link,
        "rubrique": "2",
        "titre": "Pokawa ouvre à Nantes",
        "source": "Le Média Protégé",
        "extrait": "Pokawa ouvre un restaurant à Nantes.",
        "enseigne": str(pokawa.id),
    }
    refused = post_form(web, f"{BASE}/ajouter-article/enregistrer", form)
    assert refused.status_code == 400
    assert 'id="confirme-err"' in _html(refused)
    assert 'value="Pokawa ouvre à Nantes"' in _html(refused)  # saisie conservée
    assert articles.list_for_newsletter(conn, newsletter.id) == []  # type: ignore[arg-type]

    no_title = post_form(
        web, f"{BASE}/ajouter-article/enregistrer", {**form, "titre": "", "confirme": "on"}
    )
    assert no_title.status_code == 400 and 'id="titre-err"' in _html(no_title)

    ok = post_form(web, f"{BASE}/ajouter-article/enregistrer", {**form, "confirme": "on"})
    assert ok.status_code == 302
    [added] = articles.list_for_newsletter(conn, newsletter.id)  # type: ignore[arg-type]
    assert added.link_verified_by_user is True and added.url == link
    assert added.rubric == 2 and added.brand_id == pokawa.id and added.body_text is None
    assert added.title == "Pokawa ouvre à Nantes" and added.selected
    assert "Lien vérifié par l'utilisateur</span>" in _html(web.get(f"{BASE}/rubrique-2"))


def test_manual_add_still_refuses_non_http_and_dead_links(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter, mock_http: respx.MockRouter
) -> None:
    serve(mock_http, {})
    for link in ("javascript:alert(1)", "file:///C:/secret.txt", "https://journal.example/absent"):
        response = post_form(
            web,
            f"{BASE}/ajouter-article/enregistrer",
            {"lien": link, "titre": "T", "source": "S", "confirme": "on"},
        )
        assert response.status_code == 400, link
    assert articles.list_for_newsletter(conn, newsletter.id) == []  # type: ignore[arg-type]


def test_dismissed_franchisee_filter_and_restore(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    from news_franchise.detect.runner import run_detection

    assert newsletter.id is not None
    articles.add(
        conn,
        Article(
            newsletter_id=newsletter.id,
            rubric=1,
            title="Portrait",
            source_name="Source",
            url="https://site.example/portrait",
            body_text="Jean Dupont, multi-franchisé O'Tacos à la tête de cinq restaurants à Lyon.",
        ),
    )
    run_detection(conn, "2026-10")
    [fiche] = franchisees.list_for_newsletter(conn, newsletter.id)
    assert "Fiche complète" in _html(web.get(f"{BASE}/franchises"))

    post_form(web, f"{BASE}/franchises/{fiche.id}/supprimer", {})
    assert f'id="franchise-{fiche.id}"' not in _html(web.get(f"{BASE}/franchises"))
    run_detection(conn, "2026-10")  # écarté : jamais reproposé
    assert franchisees.list_for_newsletter(conn, newsletter.id) == []
    dismissed = _html(web.get(f"{BASE}/franchises?filtre=ecartes"))
    assert f'id="franchise-{fiche.id}"' in dismissed and "Restaurer" in dismissed

    post_form(web, f"{BASE}/franchises/{fiche.id}/restaurer", {"filtre": "ecartes"})
    restored = franchisees.get(conn, fiche.id)  # type: ignore[arg-type]
    assert restored is not None and not restored.dismissed and not restored.validated
    assert f'id="franchise-{fiche.id}"' in _html(web.get(f"{BASE}/franchises"))
    assert post_form(web, f"{BASE}/franchises/{fiche.id}/restaurer", {}).status_code == 404


def test_fiche_labels(web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    for name, level in (("A Un", "haute"), ("B Deux", "moyenne"), ("C Trois", "basse")):
        fiche = _detected(conn, newsletter, name)
        conn.execute("UPDATE franchisees SET confidence = ? WHERE id = ?", (level, fiche.id))
    html = _html(web.get(f"{BASE}/franchises"))
    for label in ("Fiche complète", "Fiche partielle", "Fiche incomplète"):
        assert label in html
    assert "Confiance" not in html and "Phrase de l&#39;article" not in html


def test_security_unchanged_on_new_routes(
    web: FlaskClient, conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    article = _add(conn, newsletter, 1)
    assert (
        web.post(f"{BASE}/articles/{article.id}/rubrique", data={"cible": "2"}).status_code == 400
    )
    assert (
        web.post(f"{BASE}/articles/{article.id}/deplacer", data={"sens": "tete"}).status_code == 400
    )
    response = web.get(f"{BASE}/rubrique-1", headers={"Host": "evil.example:5000"})
    assert response.status_code == 400
