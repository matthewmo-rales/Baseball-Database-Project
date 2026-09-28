"""/team/<team_id>: validation, header, season history, roster."""
import re
import sqlite3

import pytest

from app import CSP
from app import queries as Q
from app import stats as stats_module

HANK, KURT, MOE = 900010, 900013, 900015


def get(client, url, status=200):
    resp = client.get(url)
    assert resp.status_code == status, url
    return resp.get_data(as_text=True)


@pytest.mark.parametrize("team_id", ["lad", "LAD'--", "TOOLONG", "T", "TS1", "ZZZ", "ZZZZ"])
def test_bad_or_unknown_team_is_404(client, team_id):
    body = get(client, "/team/" + team_id, 404)
    assert "Traceback" not in body


def test_path_traversal_is_404(client):
    assert client.get("/team/../x").status_code == 404
    assert client.get("/team/..%2Fx").status_code == 404


def test_bad_format_never_queries(client, monkeypatch):
    def forbidden(*args):
        raise AssertionError("queried for a malformed team_id")
    monkeypatch.setattr(stats_module, "get_team", forbidden)
    for team_id in ("lad", "LAD'--", "TOOLONG"):
        assert client.get("/team/" + team_id).status_code == 404


def test_header_and_current_name_caption(client):
    body = get(client, "/team/TSA")
    assert "<h1>Fixture Alphas</h1>" in body
    assert "AL East" in body
    assert "Names shown are current franchise names." in body


def test_season_history_uses_generated_columns_and_marks_2020(client):
    text = re.sub(r"\s+", " ", get(client, "/team/TSA"))
    row = re.search(r'season=2015">2015</a></td>(.*?)</tr>', text).group(1)
    cells = re.findall(r'<td class="num">([^<]*)', row)
    # W, L, win%, RS, RA, run diff, pythag, payroll $M, payroll vs avg
    assert cells[:8] == ["90", "72", ".556", "750", "650", "+100", ".571", "150.0"]
    assert "1.25" in cells[8]                   # 150M / mean(150M, 90M)
    assert '2020</a><span class="fn-mark">*</span>' in text
    assert "2020: 60-game season; payroll is prorated in the source." in text


def test_roster_defaults_to_latest_season(client):
    assert "Roster, 2020" in get(client, "/team/TSA")


def test_roster_excludes_multi_team_rows(client):
    body = get(client, "/team/TSA?season=2017")
    assert f'href="/player/{KURT}">Kurt Slugwell</a>' in body    # single-team row
    assert "Hank Baseline" not in body                             # 2017 is multi-team
    assert ("Players who appeared for more than one team this season are not listed: "
            "the source reports their season as one combined row.") in body


def test_roster_sorted_by_war_and_pitchers_listed(client):
    body = get(client, "/team/TSA?season=2016")
    hitters = body[body.index("<h3>Hitters</h3>"):body.index("<h3>Pitchers</h3>")]
    names = re.findall(r'<a href="/player/\d+">([^<]+)</a>', hitters)
    assert names[:3] == ["Jules Doubleplay", "Hank Baseline", "Otto Bothways"]   # 4.5, 3.0, 2.5
    pitchers = body[body.index("<h3>Pitchers</h3>"):]
    assert "Moe Innings" in pitchers and ">180.0<" in pitchers                    # ip_display


def test_roster_war_matches_q11(app, client, test_db_path):
    """Q11 also sums single-team batting + pitching WAR, so they agree exactly."""
    saved = {q.query_id: q for q in app.extensions["saved_queries"].values()}
    conn = sqlite3.connect(test_db_path)
    try:
        q11 = {(r["team"], r["season_year"]): r["team_war"]
               for r in Q.execute(conn, saved["Q11"].sql, ()).records()}
    finally:
        conn.close()
    for team, year in (("TSA", 2015), ("TSA", 2016), ("TSB", 2016)):
        body = get(client, f"/team/{team}?season={year}")
        total = re.search(r"total (-?[\d.]+)\.", body).group(1)
        assert float(total) == q11[(team, year)]


@pytest.mark.parametrize("season", ["abc", "2015.0", "1999", "-1"])
def test_bad_season_is_400(client, season):
    get(client, f"/team/TSA?season={season}", 400)


def test_payroll_not_loaded(client, test_db_path):
    conn = sqlite3.connect(test_db_path)
    with conn:
        conn.execute("UPDATE team_stats SET payroll_usd = NULL")
    conn.close()
    text = re.sub(r"\s+", " ", get(client, "/team/TSA"))
    assert "Payroll data not loaded." in text
    row = re.search(r'season=2015">2015</a></td>(.*?)</tr>', text).group(1)
    assert re.findall(r'<td class="num">([^<]*)', row)[-2:] == ["—", "—"]


def test_query_results_link_teams(client):
    body = get(client, "/query/payroll-efficiency")
    assert 'href="/team/TSA?season=2020">TSA</a>' in body
    body = get(client, "/query/team-cost-per-war")
    assert re.search(r'href="/team/TS[AB]\?season=\d{4}">TS[AB]</a>', body)
    assert client.get("/team/TSA?season=2020").status_code == 200


def test_player_page_team_links_resolve(client):
    body = get(client, f"/player/{HANK}")
    assert 'href="/team/TSA?season=2015"' in body
    assert client.get("/team/TSA?season=2015").status_code == 200


def test_team_page_csp_is_strict(client):
    assert client.get("/team/TSA").headers["Content-Security-Policy"] == CSP
