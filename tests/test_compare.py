"""/compare: validation, picker, side-by-side totals."""
import re

import pytest

HANK, IVAN, JULES, KURT, LOU, MOE, NED, OTTO = range(900010, 900018)


def get(client, query):
    resp = client.get("/compare", query_string=query)
    return resp.status_code, resp.get_data(as_text=True)


# Same rule as the saved queries: missing -> picker, present but invalid -> 400.

@pytest.mark.parametrize("query", [{}, {"p1": ""}, {"q": "zz"}])
def test_missing_p1_shows_first_player_picker(client, query):
    status, body = get(client, query)
    assert status == 200
    assert "Compare two players" in body and "First player's name" in body


def test_first_player_picker_links_to_second_step(client):
    _, body = get(client, {"q": "hank"})
    assert f'href="/compare?p1={HANK}"' in body


def test_first_player_picker_keeps_p2_and_excludes_it(client):
    _, body = get(client, {"p2": HANK, "q": "armstrong"})
    assert f'<input type="hidden" name="p2" value="{HANK}">' in body
    assert re.findall(r'href="/compare\?p1=(\d+)&amp;p2=(\d+)"', body)
    assert f'p1={HANK}&amp;' not in body


@pytest.mark.parametrize("p1", ["abc", "1.5", "0", "-3", "1;DROP"])
def test_invalid_p1_is_400(client, p1):
    status, body = get(client, {"p1": p1})
    assert status == 400
    assert "p1 must be a positive whole number." in body
    assert "Traceback" not in body


@pytest.mark.parametrize("p2", ["abc", "0", "-1"])
def test_invalid_p2_is_400(client, p2):
    status, body = get(client, {"p1": HANK, "p2": p2})
    assert status == 400
    assert "p2 must be a positive whole number." in body


def test_blank_p2_shows_second_player_picker(client):
    status, body = get(client, {"p1": HANK, "p2": ""})
    assert status == 200 and "Compare Hank Baseline" in body


def test_same_player_twice_is_400(client):
    status, body = get(client, {"p1": HANK, "p2": HANK})
    assert status == 400
    assert "Choose two different players." in body


@pytest.mark.parametrize("query", [
    {"p1": HANK, "p2": 999999},
    {"p1": 999999, "p2": HANK},
    {"p1": 999999},                   # picker for an unknown first player
    {"p2": 999999},                   # first-player picker carrying an unknown p2
])
def test_unknown_id_is_404(client, query):
    status, body = get(client, query)
    assert status == 404
    assert "There is no player with ID 999999." in body


def test_picker_form_without_q(client):
    status, body = get(client, {"p1": HANK})
    assert status == 200
    assert f'<input type="hidden" name="p1" value="{HANK}">' in body
    assert "Compare Hank Baseline" in body
    assert "<table" not in body


def test_picker_lists_matches_and_excludes_p1(client):
    status, body = get(client, {"p1": 900001, "q": "testy"})
    assert status == 200
    links = re.findall(r'href="/compare\?p1=(\d+)&amp;p2=(\d+)"', body)
    assert links == [("900001", "900002")]


def test_picker_reports_no_other_match(client):
    _, body = get(client, {"p1": HANK, "q": "hank baseline"})
    assert "No other players match" in body


def test_picker_escapes_q(client):
    _, body = get(client, {"p1": HANK, "q": "<b>x\"y"})
    assert "<b>x" not in body
    assert "&lt;b&gt;x&#34;y" in body


def test_picker_uses_search_validation(client):
    _, body = get(client, {"p1": HANK, "q": "a"})
    assert "Enter at least 2 characters." in body
    _, body = get(client, {"p1": HANK, "q": "90%"})       # same escaping as /
    assert re.findall(r"p2=(\d+)", body) == ["900004"]


def test_valid_pair_renders_side_by_side(client):
    status, body = get(client, {"p1": HANK, "p2": MOE})
    assert status == 200
    text = re.sub(r"\s+", " ", body)
    assert "Hank Baseline vs Moe Innings" in text
    assert f"ID {HANK}" in text and f"ID {MOE}" in text
    # seasons played, best-season WAR (raw) and combined WAR
    assert re.search(r"Seasons played</th> <td class=\"num\">4</td> <td class=\"num\">3</td>", text)
    assert "4.0 (2015)" in text
    assert re.search(r"Best-season WAR</th> <td class=\"num\">4.0 \(2015\)</td> <td class=\"num\">4.0 \(2015\)</td>", text)
    # same totals helper as the player page: recomputed rates
    assert ">.281<" in text and ">.344<" in text and ">3.07<" in text and ">440.0<" in text
    # one side has no batting, the other no pitching: dashes, not errors
    assert re.search(r"AVG</th> <td class=\"num\">.281</td> <td class=\"num\">—</td>", text)
    assert re.search(r"ERA</th> <td class=\"num\">—</td> <td class=\"num\">3.07</td>", text)
    assert f'data-chart-src="/compare/war-chart.json?p1={HANK}&amp;p2={MOE}"' in body


def test_two_way_combined_war(client):
    _, body = get(client, {"p1": OTTO, "p2": HANK})
    text = re.sub(r"\s+", " ", body)
    # Otto: batting 2.0 + 2.5, pitching 2.2 + 3.0 = 9.7 combined; best 5.5 in 2016
    assert re.search(r"WAR, batting \+ pitching</th> <td class=\"num\">9.7</td>", text)
    assert "5.5 (2016)" in text
