"""Tests des dépôts (newsletters, articles, franchisés, ouvertures, rencontres, collectes)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from news_franchise.config import Settings
from news_franchise.models import (
    Article,
    Franchisee,
    FrontPageFigures,
    Meeting,
    Newsletter,
    Opening,
    OpeningPhoto,
)
from news_franchise.repositories import (
    articles,
    brands,
    collection_runs,
    franchisees,
    meetings,
    newsletters,
    openings,
)


def _article(newsletter: Newsletter, url: str, title: str = "Titre", rubric: int = 1) -> Article:
    assert newsletter.id is not None
    return Article(
        newsletter_id=newsletter.id,
        rubric=rubric,
        title=title,
        source_name="Toute la Franchise",
        url=url,
        published_at=datetime(2026, 10, 7, 8, 0, tzinfo=UTC),
        excerpt="Premières lignes de l'article.",
    )


def _franchisee(newsletter: Newsletter, name: str, validated: bool = False) -> Franchisee:
    assert newsletter.id is not None
    return Franchisee(
        newsletter_id=newsletter.id,
        name=name,
        brands="Pokawa",
        source_name="Ouest-France",
        source_url="https://www.exemple.fr/article-franchise",
        validated=validated,
    )


# --------------------------------------------------------------------------- newsletters


def test_get_or_create_is_idempotent(conn: sqlite3.Connection) -> None:
    first = newsletters.get_or_create(conn, "2026-10")
    second = newsletters.get_or_create(conn, "2026-10")
    assert first == second
    assert first.id is not None and first.status == "draft"
    assert first.created_at is not None
    assert len(newsletters.list_all(conn)) == 1


@pytest.mark.parametrize("month", ["2026-13", "octobre", "2026-1", "2026-00", "", "26-10"])
def test_invalid_month(conn: sqlite3.Connection, month: str) -> None:
    with pytest.raises(ValueError, match="AAAA-MM"):
        newsletters.get_or_create(conn, month)


def test_list_all_most_recent_first(conn: sqlite3.Connection) -> None:
    for month in ("2026-09", "2026-11", "2025-12"):
        newsletters.get_or_create(conn, month)
    assert [n.month for n in newsletters.list_all(conn)] == ["2026-11", "2026-09", "2025-12"]
    assert newsletters.get(conn, "2026-01") is None


def test_status_and_plans_url(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    updated = newsletters.set_status(conn, newsletter.id, "reviewed")
    assert updated.status == "reviewed"
    with pytest.raises(ValueError):
        newsletters.set_status(conn, newsletter.id, "envoyée")
    url = "https://drive.google.com/plans-developpement"
    assert (
        newsletters.set_development_plans_url(conn, newsletter.id, url).development_plans_url == url
    )
    with pytest.raises(ValueError):
        newsletters.set_development_plans_url(conn, newsletter.id, "drive/plans")
    assert (
        newsletters.set_development_plans_url(conn, newsletter.id, None).development_plans_url
        is None
    )


# --------------------------------------------------------------------------- articles


@pytest.mark.parametrize(
    "url", ["", "   ", "ftp://site.example/a", "www.site.example/a", "/relatif", "https://"]
)
def test_article_rejects_invalid_url(newsletter: Newsletter, url: str) -> None:
    with pytest.raises(ValueError, match="http"):
        _article(newsletter, url)


def test_article_duplicate_url_same_month(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    url = "https://www.toute-la-franchise.example/actu/pokawa"
    added = articles.add(conn, _article(newsletter, url))
    assert added is not None and added.id is not None and added.position == 0
    assert added.collected_at is not None
    assert articles.add(conn, _article(newsletter, url, title="Autre titre")) is None
    assert len(articles.list_for_rubric(conn, newsletter.id, 1)) == 1  # type: ignore[arg-type]

    november = newsletters.get_or_create(conn, "2026-11")
    assert articles.add(conn, _article(november, url)) is not None


def test_sql_check_blocks_direct_invalid_insert(
    conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO articles (newsletter_id, rubric, title, source_name, url, collected_at)"
            " VALUES (?, 1, 'Titre', 'Source', ?, '2026-10-09T00:00:00+00:00')",
            (newsletter.id, "javascript:alert(1)"),
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO franchisees (newsletter_id, name, source_name, source_url)"
            " VALUES (?, 'X', 'Source', '')",
            (newsletter.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO articles (newsletter_id, rubric, title, source_name, url, collected_at)"
            " VALUES (?, 3, 'Titre', 'Source', 'https://a.example/', 'x')",
            (newsletter.id,),
        )


def test_sql_injection_text_is_stored_verbatim(
    conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    title = "'); DROP TABLE articles; --"
    added = articles.add(conn, _article(newsletter, "https://a.example/x", title=title))
    assert added is not None and added.id is not None
    assert articles.get(conn, added.id).title == title  # type: ignore[union-attr]
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1


def test_reorder_and_list(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    ids = [
        articles.add(conn, _article(newsletter, f"https://a.example/{i}", title=f"A{i}")).id  # type: ignore[union-attr]
        for i in range(4)
    ]
    other_rubric = articles.add(conn, _article(newsletter, "https://a.example/r2", rubric=2))
    assert other_rubric is not None and other_rubric.position == 0  # numérotation par rubrique

    articles.reorder(conn, newsletter.id, 1, [ids[3], ids[1]])
    listed = articles.list_for_rubric(conn, newsletter.id, 1)
    assert [a.id for a in listed] == [ids[3], ids[1], ids[0], ids[2]]
    assert [a.position for a in listed] == [0, 1, 2, 3]

    with pytest.raises(ValueError, match="inconnus"):
        articles.reorder(conn, newsletter.id, 1, [other_rubric.id])  # type: ignore[list-item]


def test_update_select_delete(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    a = articles.add(conn, _article(newsletter, "https://a.example/1"))
    b = articles.add(conn, _article(newsletter, "https://a.example/2"))
    assert a is not None and b is not None and a.id is not None and b.id is not None

    a.title = "Nouveau titre"
    a.is_opportunity = True
    updated = articles.update(conn, a)
    assert updated.title == "Nouveau titre" and updated.is_opportunity is True
    assert updated.published_at == datetime(2026, 10, 7, 8, 0, tzinfo=UTC)

    b.url = a.url
    with pytest.raises(ValueError, match="déjà ce lien"):
        articles.update(conn, b)

    articles.set_selected(conn, a.id, False)
    assert [x.id for x in articles.list_for_rubric(conn, newsletter.id, 1, selected_only=True)] == [
        b.id
    ]

    articles.delete(conn, a.id)
    assert articles.get(conn, a.id) is None


# --------------------------------------------------------------------------- franchisés


def test_franchisees(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    source = articles.add(conn, _article(newsletter, "https://a.example/source"))
    assert source is not None
    f1 = franchisees.add(conn, _franchisee(newsletter, "Groupe Martin"))
    f2 = franchisees.add(conn, _franchisee(newsletter, "SAS Durand"))
    assert f1.id is not None and f2.id is not None
    assert f1.store_count is None  # souvent inconnu

    f1.article_id = source.id
    f1.store_count = 12
    f1.location = "Lyon"
    assert franchisees.update(conn, f1).store_count == 12

    franchisees.set_validated(conn, f2.id, True)
    assert [
        f.name for f in franchisees.list_for_newsletter(conn, newsletter.id, validated_only=True)
    ] == ["SAS Durand"]
    franchisees.reorder(conn, newsletter.id, [f2.id, f1.id])
    assert [f.id for f in franchisees.list_for_newsletter(conn, newsletter.id)] == [f2.id, f1.id]

    # Suppression de l'article source : le franchisé reste, article_id devient NULL.
    articles.delete(conn, source.id)  # type: ignore[arg-type]
    assert franchisees.get(conn, f1.id).article_id is None  # type: ignore[union-attr]

    with pytest.raises(ValueError):
        Franchisee(newsletter_id=newsletter.id, name="X", source_name="S", source_url="pas-un-lien")
    with pytest.raises(ValueError):
        Franchisee(
            newsletter_id=newsletter.id,
            name="X",
            source_name="S",
            source_url="https://a.example/",
            store_count=-1,
        )

    franchisees.delete(conn, f1.id)
    assert franchisees.get(conn, f1.id) is None


# --------------------------------------------------------------------------- ouvertures et photos


def test_openings_and_photos(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    assert newsletter.id is not None
    opening = openings.add(
        conn,
        Opening(
            newsletter_id=newsletter.id,
            brand_name="Pokawa",
            location="Centre commercial de Lyon",
            opening_date=date(2026, 10, 2),
        ),
    )
    assert opening.id is not None
    assert openings.get(conn, opening.id).opening_date == date(2026, 10, 2)  # type: ignore[union-attr]

    photo_file = settings.photos_dir / "2026-10" / "pokawa.jpg"
    photo_file.parent.mkdir(parents=True)
    photo_file.write_bytes(b"jpeg")
    photo = openings.add_photo(
        conn, OpeningPhoto(opening_id=opening.id, file_name="2026-10/pokawa.jpg")
    )
    assert photo.id is not None
    assert [p.file_name for p in openings.list_photos(conn, opening.id)] == ["2026-10/pokawa.jpg"]

    openings.delete_photo(conn, photo.id, settings.photos_dir)
    assert not photo_file.exists()
    assert openings.list_photos(conn, opening.id) == []

    # Fichier déjà disparu : pas d'erreur.
    ghost = openings.add_photo(conn, OpeningPhoto(opening_id=opening.id, file_name="absente.jpg"))
    openings.delete_photo(conn, ghost.id, settings.photos_dir)  # type: ignore[arg-type]
    assert openings.list_photos(conn, opening.id) == []


@pytest.mark.parametrize(
    "file_name",
    ["", "/tmp/photo.jpg", "C:\\Users\\photo.jpg", "C:/photo.jpg", "../photo.jpg", "a/../../b.jpg"],
)
def test_photo_file_name_must_be_relative(file_name: str) -> None:
    with pytest.raises(ValueError, match="relatif"):
        OpeningPhoto(opening_id=1, file_name=file_name)


def test_sql_check_blocks_absolute_photo_path(
    conn: sqlite3.Connection, newsletter: Newsletter
) -> None:
    opening = openings.add(conn, Opening(newsletter_id=newsletter.id, brand_name="A", location="B"))  # type: ignore[arg-type]
    for bad in ("/etc/passwd", "C:\\photo.jpg", "../x.jpg"):
        with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
            conn.execute(
                "INSERT INTO opening_photos (opening_id, file_name) VALUES (?, ?)",
                (opening.id, bad),
            )


def test_meetings_and_openings_order(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    m1 = meetings.add(conn, Meeting(newsletter_id=newsletter.id, brand_name="Leonidas"))
    m2 = meetings.add(
        conn,
        Meeting(newsletter_id=newsletter.id, brand_name="Wycon", meeting_date=date(2026, 10, 5)),
    )
    meetings.reorder(conn, newsletter.id, [m2.id, m1.id])  # type: ignore[list-item]
    listed = meetings.list_for_newsletter(conn, newsletter.id)
    assert [m.brand_name for m in listed] == ["Wycon", "Leonidas"]
    assert listed[0].meeting_date == date(2026, 10, 5)
    m1.comment = "Intéressée par Lyon"
    assert meetings.update(conn, m1).comment == "Intéressée par Lyon"
    meetings.delete(conn, m1.id)  # type: ignore[arg-type]
    assert len(meetings.list_for_newsletter(conn, newsletter.id)) == 1

    o1 = openings.add(conn, Opening(newsletter_id=newsletter.id, brand_name="A", location="Lyon"))
    o2 = openings.add(conn, Opening(newsletter_id=newsletter.id, brand_name="B", location="Nice"))
    openings.reorder(conn, newsletter.id, [o2.id, o1.id])  # type: ignore[list-item]
    assert [o.brand_name for o in openings.list_for_newsletter(conn, newsletter.id)] == ["B", "A"]
    o1.description = "Ouverture réussie"
    assert openings.update(conn, o1).description == "Ouverture réussie"


# --------------------------------------------------------------------------- Une et cascades


def test_front_page_figures(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    assert newsletters.front_page_figures(conn, newsletter.id) == FrontPageFigures(0, 0, 0)

    openings.add(conn, Opening(newsletter_id=newsletter.id, brand_name="Pokawa", location="Lyon"))
    openings.add(conn, Opening(newsletter_id=newsletter.id, brand_name="Pokawa", location="Nice"))
    for name in ("Leonidas", "Wycon", "leonidas "):
        meetings.add(conn, Meeting(newsletter_id=newsletter.id, brand_name=name))
    franchisees.add(conn, _franchisee(newsletter, "Validé", validated=True))
    franchisees.add(conn, _franchisee(newsletter, "Non validé"))

    figures = newsletters.front_page_figures(conn, newsletter.id)
    assert figures == FrontPageFigures(openings=2, brands_met=2, franchisees=1)

    other = newsletters.get_or_create(conn, "2026-11")
    assert newsletters.front_page_figures(conn, other.id) == FrontPageFigures(0, 0, 0)  # type: ignore[arg-type]


def test_delete_newsletter_cascades(
    conn: sqlite3.Connection, newsletter: Newsletter, settings: Settings
) -> None:
    nid = newsletter.id
    assert nid is not None
    articles.add(conn, _article(newsletter, "https://a.example/1"))
    franchisees.add(conn, _franchisee(newsletter, "Groupe Martin"))
    opening = openings.add(conn, Opening(newsletter_id=nid, brand_name="A", location="Lyon"))
    photo_file = settings.photos_dir / "a.jpg"
    photo_file.write_bytes(b"jpeg")
    openings.add_photo(conn, OpeningPhoto(opening_id=opening.id, file_name="a.jpg"))  # type: ignore[arg-type]
    meetings.add(conn, Meeting(newsletter_id=nid, brand_name="Wycon"))
    run = collection_runs.start(conn, nid)

    newsletters.delete(conn, nid, settings.photos_dir)

    for table in (
        "articles",
        "franchisees",
        "openings",
        "opening_photos",
        "meetings",
        "collection_runs",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table
    assert newsletters.get(conn, "2026-10") is None
    assert collection_runs.get(conn, run.id) is None  # type: ignore[arg-type]
    assert not photo_file.exists()


def test_remove_photo_file_never_leaves_photos_dir(tmp_path: Path) -> None:
    photos_dir = tmp_path / "photos"
    photos_dir.mkdir()
    outside = tmp_path / "important.txt"
    outside.write_text("x", encoding="utf-8")
    openings.remove_photo_file(photos_dir, "../important.txt")
    assert outside.exists()


# --------------------------------------------------------------------------- collectes


def test_collection_runs(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    assert newsletter.id is not None
    assert collection_runs.last_for_newsletter(conn, newsletter.id) is None
    run = collection_runs.start(conn, newsletter.id)
    assert run.status == "running" and run.id is not None

    finished = collection_runs.finish(
        conn, run.id, "partial", {"articles": 12}, ["AC Franchise : délai dépassé."]
    )
    assert finished.status == "partial"
    assert finished.finished_at is not None
    assert finished.stats == {"articles": 12}
    assert finished.errors == ["AC Franchise : délai dépassé."]
    assert collection_runs.last_for_newsletter(conn, newsletter.id) == finished
    with pytest.raises(ValueError):
        collection_runs.finish(conn, run.id, "running")


def test_articles_can_reference_brand(conn: sqlite3.Connection, newsletter: Newsletter) -> None:
    brands.sync_from_yaml(conn)
    pokawa = brands.get_by_name(conn, "Pokawa")
    assert pokawa is not None
    article = _article(newsletter, "https://a.example/pokawa", rubric=2)
    article.brand_id = pokawa.id
    article.sector = pokawa.sector
    added = articles.add(conn, article)
    assert added is not None and added.brand_id == pokawa.id
