"""Tests de l'évaluation des flux et de Google Actualités."""

from __future__ import annotations

from datetime import timedelta

import httpx
import respx

from news_franchise.http_client import Fetcher
from news_franchise.sources.evaluation import (
    EXPLOITABLE,
    GOOGLE_LINK_ONLY,
    PARTIAL,
    RESOLVED,
    UNUSABLE,
    build_google_news_url,
    evaluate_feed,
    evaluate_google_news,
)
from tests.helpers import NOW, html, rss, serve

FEED = "https://franchise-test.example/actus/rss.xml"
ARTICLES = "https://franchise-test.example/articles/"


def _articles_ok(router: respx.MockRouter) -> None:
    """Les pages d'articles répondent 200."""
    router.get(url__startswith=ARTICLES).mock(return_value=httpx.Response(200, text="article"))


def test_complete_recent_feed_is_exploitable(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    _articles_ok(mock_http)
    serve(mock_http, {FEED: rss("rss_complete.xml")})

    report = evaluate_feed(FEED, fetcher=fetcher, now=NOW)

    assert report.verdict == EXPLOITABLE, report.reason
    assert report.entry_count == 4
    assert report.recent_count == 3  # 07/10, 01/10 et 21/09 ; pas le 20/03
    assert report.latest_entry is not None
    assert report.latest_entry.strftime("%Y-%m-%d") == "2026-10-07"
    assert report.share_title == report.share_date == report.share_link == 1.0
    assert report.sample_titles == [
        "Pokawa ouvre son 100e restaurant",
        "Leonidas accélère en franchise",
        "Easy Cash : bilan du semestre",
    ]
    assert len(report.link_checks) == 3
    assert all(check.ok for check in report.link_checks)


def test_recent_count_depends_on_injected_date(
    mock_http: respx.MockRouter, fetcher: Fetcher
) -> None:
    _articles_ok(mock_http)
    serve(mock_http, {FEED: rss("rss_complete.xml")})

    report = evaluate_feed(FEED, fetcher=fetcher, now=NOW + timedelta(days=365))

    assert report.recent_count == 0
    assert report.verdict == PARTIAL
    assert "aucun article depuis 30 jours" in report.reason
    assert "07/10/2026" in report.reason


def test_feed_without_dates_is_partial(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    feed = "https://nodates.example/rss"
    mock_http.get(url__startswith="https://nodates.example/article").mock(
        return_value=httpx.Response(200)
    )
    serve(mock_http, {feed: rss("rss_no_dates.xml")})

    report = evaluate_feed(feed, fetcher=fetcher, now=NOW)

    assert report.verdict == PARTIAL
    assert "date (0 % des articles en ont)" in report.reason
    assert "aucune date de publication" in report.reason


def test_broken_article_links_make_feed_partial(
    mock_http: respx.MockRouter, fetcher: Fetcher
) -> None:
    serve(mock_http, {FEED: rss("rss_complete.xml")})  # articles → 404 (repli)

    report = evaluate_feed(FEED, fetcher=fetcher, now=NOW)

    assert report.verdict == PARTIAL
    assert "3 lien(s) testé(s) sur 3 en erreur" in report.reason
    assert "HTTP 404" in report.reason


def test_empty_feed_is_unusable(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    feed = "https://empty.example/rss"
    serve(mock_http, {feed: rss("rss_empty.xml")})
    report = evaluate_feed(feed, fetcher=fetcher, now=NOW)
    assert report.verdict == UNUSABLE
    assert report.reason == "Le flux est vide (aucun article)."


def test_404_feed_is_unusable(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    serve(mock_http, {})
    report = evaluate_feed("https://gone.example/rss", fetcher=fetcher, now=NOW)
    assert report.verdict == UNUSABLE
    assert report.http_status == 404
    assert "HTTP 404" in report.reason


def test_html_instead_of_feed_is_unusable(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    feed = "https://html.example/rss"
    serve(mock_http, {feed: html("site_without_feed.html")})
    report = evaluate_feed(feed, fetcher=fetcher, now=NOW)
    assert report.verdict == UNUSABLE
    assert "pas un flux" in report.reason


def test_google_news_url_encoding() -> None:
    assert build_google_news_url("O'Tacos") == (
        "https://news.google.com/rss/search?q=%22O%27Tacos%22%20when%3A30d"
        "&hl=fr&gl=FR&ceid=FR:fr"
    )
    assert build_google_news_url("Dunkin' Donuts") == (
        "https://news.google.com/rss/search?q=%22Dunkin%27%20Donuts%22%20when%3A30d"
        "&hl=fr&gl=FR&ceid=FR:fr"
    )
    assert "%22Cr%C3%AApe%20Touch%22" in build_google_news_url("Crêpe Touch")


def test_google_news_link_only(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    url = build_google_news_url("O'Tacos")
    # La page d'article Google répond 200 sans rediriger vers l'éditeur.
    mock_http.get(url__startswith="https://news.google.com/rss/articles/").mock(
        return_value=httpx.Response(200, text="<html>redirection JavaScript</html>")
    )
    serve(mock_http, {url: rss("google_news.xml")})

    report = evaluate_google_news("O'Tacos", fetcher=fetcher, now=NOW)

    assert report.kind == "google_news"
    assert report.query == '"O\'Tacos" when:30d'
    assert report.verdict == EXPLOITABLE, report.reason
    assert report.link_resolution == GOOGLE_LINK_ONLY
    assert report.publishers == [("Le Progrès", 2), ("Ouest-France", 1)]
    assert report.recent_count == 3


def test_google_news_resolved(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    url = build_google_news_url("O'Tacos")
    publisher = "https://editeur.example/article"
    mock_http.get(url__startswith="https://news.google.com/rss/articles/").mock(
        return_value=httpx.Response(302, headers={"location": publisher})
    )
    serve(mock_http, {url: rss("google_news.xml"), publisher: httpx.Response(200)})

    report = evaluate_google_news("O'Tacos", fetcher=fetcher, now=NOW)

    assert report.link_resolution == RESOLVED
    assert report.link_checks[0].final_url == publisher


def test_google_news_no_result(mock_http: respx.MockRouter, fetcher: Fetcher) -> None:
    serve(mock_http, {build_google_news_url("Wycon"): rss("google_news_empty.xml")})
    report = evaluate_google_news("Wycon", fetcher=fetcher, now=NOW)
    assert report.verdict == UNUSABLE
    assert "Aucun article" in report.reason
