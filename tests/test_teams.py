"""/team/<team_id>: validation, header, season history, roster."""
import re
import sqlite3

import pytest

from app import CSP
from app import queries as Q
from app import stats as stats_module
from tests.conftest import query_db

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


# ---------------------------------------------------------------- /teams

TEAM_LINK = re.compile(r'<a href="/team/(TS[A-Z])">')
FIXTURE_ORDER = [  # AL East, AL Central, AL West, NL Central; names alphabetical
    ("AL", "East", ["TSA", "TSB"]),
    ("AL", "Central", ["TSE", "TSF"]),     # Fixture Q_Stars < Fixture QxStars
    ("AL", "West", ["TSC", "TSD"]),        # Fixture 50% Club < Fixture 500 Club
    ("NL", "Central", ["TSG"]),
]


def team_sections(body):
    """{(league, division): [team ids]} in page order, from the h2/h3 headings."""
    out, league = [], None
    for m in re.finditer(r"<h2>([^<]+)</h2>|<h3>([^<]+)</h3>|" + TEAM_LINK.pattern, body):
        if m.group(1):
            league = m.group(1)
        elif m.group(2):
            lg, division = m.group(2).split(" ", 1)
            assert lg == league
            out.append((league, division, []))
        else:
            out[-1][2].append(m.group(3))
    return out


def teams_page(client, q=None, status=200):
    resp = client.get("/teams", query_string={"q": q} if q is not None else {})
    assert resp.status_code == status, q
    return resp


def test_teams_lists_every_team_grouped_and_ordered(client, test_db_path):
    body = teams_page(client).get_data(as_text=True)
    assert "<h1>Teams</h1>" in body
    assert team_sections(body) == FIXTURE_ORDER
    db_ids = {r[0] for r in query_db(test_db_path, "SELECT team_id FROM teams")}
    assert set(TEAM_LINK.findall(body)) == db_ids
    assert '<span class="badge mono">TSA</span> <a href="/team/TSA">Fixture Alphas</a>' in body
    assert "match" not in body                       # no count line without a search


def test_team_list_row_shows_city_unless_name_starts_with_it(client):
    body = teams_page(client).get_data(as_text=True)
    assert ('<span class="badge mono">TSG</span> <a href="/team/TSG">Fixture Gammas</a>'
            ' <span class="team-city">Tsarville</span></li>') in body
    # TSD's city is "Fixture" and its name is "Fixture 500 Club": no repeat.
    assert '<a href="/team/TSD">Fixture 500 Club</a></li>' in body
    assert '<span class="team-city">Fixture</span>' not in body
    # Display only: search still matches on city (Tsarville is in no name).
    assert teams_page(client, "tsarville", 302).headers["Location"] == "/team/TSG"


def test_partial_name_match_redirects(client):
    resp = teams_page(client, "alph", 302)
    assert resp.headers["Location"] == "/team/TSA"


def test_city_match_redirects(client):
    assert teams_page(client, "underscore", 302).headers["Location"] == "/team/TSE"


def test_lowercase_abbreviation_redirects_to_uppercase_id(client):
    assert teams_page(client, "tsg", 302).headers["Location"] == "/team/TSG"
    assert teams_page(client, " tsb ", 302).headers["Location"] == "/team/TSB"


def test_exact_abbreviation_wins_over_name_and_city_matches(client):
    """'tsa' is TSA's id and also inside TSG's city, Tsarville. Real case: 'lad'
    is inside 'Philadelphia'."""
    for q in ("tsa", "TSA", " Tsa "):
        assert teams_page(client, q, 302).headers["Location"] == "/team/TSA"
    assert teams_page(client, "tsar", 302).headers["Location"] == "/team/TSG"   # not an id: substring


def test_abbreviation_is_exact_not_substring(client):
    body = teams_page(client, "sb").get_data(as_text=True)      # inside TSB, in no name or city
    assert "No teams match" in body


def test_shared_city_lists_both_teams(client):
    body = teams_page(client, "mocktown").get_data(as_text=True)
    assert "2 matches for &ldquo;mocktown&rdquo;." in body
    assert team_sections(body) == [("AL", "East", ["TSA", "TSB"])]


def test_multi_match_keeps_grouping(client):
    body = teams_page(client, "fixture").get_data(as_text=True)
    assert "7 matches for &ldquo;fixture&rdquo;." in body
    assert team_sections(body) == FIXTURE_ORDER


def test_no_match_notice_links_back(client):
    body = teams_page(client, "zzz").get_data(as_text=True)
    assert "No teams match &ldquo;zzz&rdquo;." in body
    assert '<a href="/teams">Show all teams</a>' in body
    assert not TEAM_LINK.findall(body)


@pytest.mark.parametrize("q, expected", [
    ("0%", "/team/TSC"),      # a wildcard would also match "Fixture 500 Club"
    ("q_", "/team/TSE"),      # a wildcard would also match "Fixture QxStars"
    ("０％", "/team/TSC"),     # fullwidth, normalized before escaping
    ("ｑ＿", "/team/TSE"),
])
def test_percent_and_underscore_match_literally(client, q, expected):
    assert teams_page(client, q, 302).headers["Location"] == expected


@pytest.mark.parametrize("q", ["\\%", "\\_", "\\\\"])
def test_backslash_matches_literally(client, q):
    # unescaped, "\%" and "\_" would match the 50% and Q_ teams
    body = teams_page(client, q).get_data(as_text=True)
    assert "No teams match" in body


@pytest.mark.parametrize("q", ["", "   ", "\t"])
def test_blank_query_shows_full_list(client, q):
    body = teams_page(client, q).get_data(as_text=True)
    assert team_sections(body) == FIXTURE_ORDER
    assert "notice" not in body


@pytest.mark.parametrize("q, message", [
    ("m", "Enter at least 2 characters."),
    ("x" * 51, "Search is limited to 50 characters."),
])
def test_bad_length_shows_notice_then_full_list(client, monkeypatch, q, message):
    from app import teams
    monkeypatch.setattr(teams, "SEARCH_TEAMS_SQL", "SELECT forbidden")   # no search SQL runs
    body = teams_page(client, q).get_data(as_text=True)
    assert f'<p class="notice">{message}</p>' in body
    assert team_sections(body) == FIXTURE_ORDER


def test_search_box_matches_player_search_limits(client):
    body = teams_page(client).get_data(as_text=True)
    assert 'role="search"' in body and 'method="get"' in body
    assert '<label for="q">Team name, city or abbreviation</label>' in body
    assert 'maxlength="50"' in body


def test_redirect_uses_db_id_not_input(client):
    """Location comes from the row, so input casing or padding never leaks in."""
    for q in ("Tsa", "tSa", "FIXTURE ALPHAS", "fixture alphas "):
        loc = teams_page(client, q, 302).headers["Location"]
        assert loc == "/team/TSA"


def test_every_redirect_is_a_same_host_team_path(client):
    for q in ("alph", "tsg", "0%", "q_", "gammas", "percent falls", "tsarville"):
        loc = teams_page(client, q, 302).headers["Location"]
        assert re.fullmatch(r"/team/[A-Z]{2,4}", loc), loc
        assert client.get(loc).status_code == 200


def test_team_page_still_rejects_lowercase(client):
    assert client.get("/team/tsa").status_code == 404


def test_nav_and_index_link_to_teams(client):
    body = client.get("/").get_data(as_text=True)
    nav = body[body.index('<nav class="site-nav"'):body.index("</nav>")]
    assert nav.index(">Player search<") < nav.index('href="/teams">Teams<')
    form_end = body.index("</form>")
    assert body.index('<a href="/teams">', form_end) > form_end
