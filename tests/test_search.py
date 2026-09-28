import re

import pytest

from app import create_app
from app.db import search_key
from app.main import like_pattern
from tests.conftest import REAL_DB

ID_CELL = re.compile(r'<td class="num">(9\d{5})</td>')


def ids_for(client, q):
    resp = client.get("/", query_string={"q": q})
    assert resp.status_code == 200
    return ID_CELL.findall(resp.get_data(as_text=True))


def test_empty_query_shows_form_only(client):
    resp = client.get("/")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'name="q"' in body
    assert "<table" not in body


def test_duplicate_name_returns_two_distinct_ids(client):
    assert ids_for(client, "testy mcfakerson") == ["900001", "900002"]


def test_unaccented_query_finds_accented_name(client):
    resp = client.get("/", query_string={"q": "zoe ficticia"})
    body = resp.get_data(as_text=True)
    assert ID_CELL.findall(body) == ["900003"]
    assert "Zoë Fictíciá" in body


def test_accented_query_finds_accented_name(client):
    assert ids_for(client, "ZOË") == ["900003"]


def test_percent_matches_literally(client):
    # unescaped, '%90%%' would also match 'Zed 900 Fictional'
    assert ids_for(client, "90%") == ["900004"]


def test_underscore_matches_literally(client):
    # unescaped, '_' would also match the 'x' in 'Zed QxFictional'
    assert ids_for(client, "q_f") == ["900006"]


def test_fullwidth_wildcards_cannot_sneak_past_escaping(client):
    # NFKD turns U+FF05 / U+FF3F into '%' / '_'; they must still be literal
    assert ids_for(client, "90％") == ["900004"]
    assert ids_for(client, "q＿f") == ["900006"]


def test_backslash_is_literal(client):
    assert ids_for(client, "zed\\") == []


def test_first_and_last_season_span_both_stat_tables(client):
    body = client.get("/", query_string={"q": "mcfakerson"}).get_data(as_text=True)
    assert "2015&ndash;2017" in body  # 900001: batting 2015-16, pitching 2017
    assert "2016&ndash;2017" in body  # 900002: pitching 2016-17, 0-PA batting 2017


def test_birth_year_and_links(client):
    body = client.get("/", query_string={"q": "mcfakerson"}).get_data(as_text=True)
    assert '<a href="/player/900001">' in body
    assert "1990" in body and "1996" in body


def test_no_match_message(client):
    body = client.get("/", query_string={"q": "nobody here"}).get_data(as_text=True)
    assert "No players match" in body


@pytest.mark.parametrize("q", ["a", " a ", "x" * 51])
def test_bad_length_shows_friendly_message(client, q):
    resp = client.get("/", query_string={"q": q})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'class="notice"' in body
    assert "<table" not in body


def test_length_bounds_are_inclusive(client):
    assert client.get("/", query_string={"q": "ze"}).status_code == 200
    body = client.get("/", query_string={"q": "z" * 50}).get_data(as_text=True)
    assert "No players match" in body


def test_search_key():
    assert search_key("José Ramírez") == "jose ramirez"
    assert search_key(None) is None
    assert like_pattern("a%b_c\\") == r"%a\%b\_c\\%"


@pytest.mark.skipif(not REAL_DB.is_file(), reason="database/baseball.db not built")
def test_real_db_will_smith_is_two_players():
    app = create_app({"TESTING": True, "SECRET_KEY": "test-only-not-secret"})
    body = app.test_client().get("/", query_string={"q": "Will Smith"}).get_data(as_text=True)
    ids = set(re.findall(r'<a href="/player/(\d+)">Will Smith</a>', body))
    assert len(ids) == 2
