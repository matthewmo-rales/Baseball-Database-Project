"""Saved-query charts, the post-query season filter, id validation, CSP."""
import html
import json
import re
import sqlite3

import pytest

from app import CSP, charts
from app import queries as Q

HANK, IVAN = 900010, 900011


def saved_by_id(app, query_id):
    return next(q for q in app.extensions["saved_queries"].values() if q.query_id == query_id)


def run(app, db_path, query_id):
    conn = sqlite3.connect(db_path)
    try:
        return Q.execute(conn, saved_by_id(app, query_id).sql, ())
    finally:
        conn.close()


def fig(client, url, status=200):
    resp = client.get(url)
    assert resp.status_code == status, url
    return json.loads(resp.get_data(as_text=True)) if status == 200 else None


def points(trace):
    return list(zip(trace["x"], trace["y"]))


# ---------------------------------------------------------------- (a) Q01 wOBA leaderboard

def test_woba_chart_defaults_to_latest_season_and_matches_q01(app, client, test_db_path):
    rows = [r for r in run(app, test_db_path, "Q01").records() if r["season_year"] == 2020]
    f = fig(client, "/query/top-woba-by-season/chart.json")
    (bar,) = f["data"]
    assert bar["type"] == "bar" and bar["orientation"] == "h"
    assert f["layout"]["title"]["text"] == "Top wOBA, qualified hitters, 2020"
    assert f["layout"]["yaxis"]["ticktext"] == [r["name"] for r in rows]
    assert bar["x"] == [r["woba"] for r in rows]
    assert [c[0] for c in bar["customdata"]] == [r["woba_rank"] for r in rows]
    assert [c[2] for c in bar["customdata"]] == [r["team"] for r in rows]
    assert f["layout"]["xaxis"]["title"]["text"] == "wOBA"


def test_woba_chart_for_a_chosen_season(app, client, test_db_path):
    rows = [r for r in run(app, test_db_path, "Q01").records() if r["season_year"] == 2015]
    f = fig(client, "/query/top-woba-by-season/chart.json?season=2015")
    assert f["layout"]["yaxis"]["ticktext"] == [r["name"] for r in rows]
    assert f["data"][0]["x"] == [r["woba"] for r in rows]
    assert f["layout"]["yaxis"]["ticktext"][0] == "Kurt Slugwell"       # .400 leads 2015


def test_woba_bars_keep_duplicate_names_apart():
    result = Q.Result(["season_year", "woba_rank", "name", "team", "pa", "woba", "wrc_plus"],
                      [(2015, 1, "Same Name", "TSA", 600, .400, 150),
                       (2015, 2, "Same Name", "TSB", 600, .390, 145)], 0)
    f = charts.woba_leaderboard(result).to_plotly_json()
    assert list(f["data"][0]["y"]) == [0, 1]


# ---------------------------------------------------------------- (b) Q03 payroll vs win%

def test_payroll_chart_all_seasons_with_hollow_2020(app, client, test_db_path):
    rows = run(app, test_db_path, "Q03").records()
    f = fig(client, "/query/payroll-efficiency/chart.json")
    full, short = f["data"]
    assert full["marker"]["symbol"] == "circle"
    assert short["marker"]["symbol"] == "circle-open"
    assert short["name"] == "2020 (60 games, prorated payroll)"
    assert len(full["x"]) + len(short["x"]) == len(rows) == 8
    assert {c[1] for c in short["customdata"]} == {2020} and len(short["x"]) == 2
    plotted = sorted((c[0], c[1], x, y) for t in f["data"] for c, x, y in
                     zip(t["customdata"], t["x"], t["y"]))
    assert plotted == sorted((r["team"], r["season_year"], r["payroll_vs_league_avg"], r["win_pct"])
                             for r in rows)
    assert "payroll_millions" not in json.dumps(f)            # hover uses values, not names
    assert all(t["mode"] == "markers" for t in f["data"])      # no trendline
    assert "league average" in f["layout"]["xaxis"]["title"]["text"]
    assert f["layout"]["yaxis"]["title"]["text"] == "Win %"


def test_payroll_chart_one_season(client):
    f = fig(client, "/query/payroll-efficiency/chart.json?season=2015")
    assert [t["name"] for t in f["data"]] == ["2015"] and len(f["data"][0]["x"]) == 2
    f = fig(client, "/query/payroll-efficiency/chart.json?season=2020")
    assert [t["marker"]["symbol"] for t in f["data"]] == ["circle-open"]


def test_payroll_chart_404_when_payroll_not_loaded(client, test_db_path):
    conn = sqlite3.connect(test_db_path)
    with conn:
        conn.execute("UPDATE team_stats SET payroll_usd = NULL")
    conn.close()
    fig(client, "/query/payroll-efficiency/chart.json", 404)
    body = client.get("/charts").get_data(as_text=True)
    assert "Payroll data not loaded." in body
    assert 'data-chart-src="/query/payroll-efficiency/chart.json"' not in body


# ---------------------------------------------------------------- (c) Q16 age curves

def test_age_curves_plot_q16_values(app, client, test_db_path):
    rows = run(app, test_db_path, "Q16").records()
    f = fig(client, "/query/aging-curves/chart.json")
    groups = sorted({r["pos_group"] for r in rows})
    assert len(f["data"]) == 2 * len(groups) == 4
    for line, markers in zip(f["data"][::2], f["data"][1::2]):
        mine = [r for r in rows if r["pos_group"] == line["name"]]
        assert line["mode"] == "lines" and markers["mode"] == "markers"
        assert line["x"] == [r["age"] for r in mine]
        assert line["y"] == [r["smoothed_change"] for r in mine]            # smoothed = line
        assert markers["y"] == [r["avg_change_into_age"] for r in mine]     # raw = markers
        assert [c[0] for c in markers["customdata"]] == [r["n_pairs"] for r in mine]
    assert f["data"][0]["line"]["dash"] != f["data"][2]["line"]["dash"]
    assert f["layout"]["xaxis"]["title"]["text"] == "Age"
    assert "cumulative" not in json.dumps(f).lower()


def test_age_curves_caption_points_to_caveats(client):
    text = re.sub(r"\s+", " ", client.get("/query/aging-curves").get_data(as_text=True))
    section = text.split('<section class="chart-section">')[1].split("</section>")[0]
    assert "delta method" in section and "survivorship bias" in section
    assert "2015&ndash;2025 window" in section
    assert "peak" not in section.lower()          # no peak-age claims in UI text


# ---------------------------------------------------------------- (d) Q10 birth cohorts

def test_birth_cohort_chart_matches_q10(app, client, test_db_path):
    rows = sorted(run(app, test_db_path, "Q10").records(), key=lambda r: r["birth_year"])
    assert rows                                     # the fixture's 1990 cohort
    f = fig(client, "/query/birth-cohort-war/chart.json")
    (bar,) = f["data"]
    assert bar["x"] == [r["birth_year"] for r in rows]
    assert bar["y"] == [r["total_war"] for r in rows]
    assert [c[0] for c in bar["customdata"]] == [r["avg_war_per_player"] for r in rows]
    assert "birth cohort" in f["layout"]["title"]["text"]
    assert "draft" not in json.dumps(f).lower()


def test_birth_cohort_truncation_caption_is_prominent(client):
    body = client.get("/query/birth-cohort-war").get_data(as_text=True)
    assert re.search(r'<p class="notice"><strong>The 2015&ndash;2025 window truncates careers: older cohorts are '
                     r'missing early seasons,\s+younger cohorts later ones.</strong></p>', body)


# ---------------------------------------------------------------- endpoints

@pytest.mark.parametrize("url", [
    "/query/war-streaks/chart.json",            # a real query with no chart
    "/query/career-war-trajectory/chart.json",  # parameterized, no chart
    "/query/no-such-query/chart.json",
])
def test_no_chart_is_404(client, url):
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("url", [
    "/query/top-woba-by-season/chart.json?season=abc",
    "/query/top-woba-by-season/chart.json?season=1999",
    "/query/payroll-efficiency/chart.json?season=2015;DROP",
    "/query/aging-curves/chart.json?season=2015",        # Q16 has no season column
])
def test_chart_season_validation(client, url):
    assert client.get(url).status_code == 400


def test_chart_renders_above_results_on_query_page(client):
    body = client.get("/query/payroll-efficiency").get_data(as_text=True)
    assert body.index('data-chart-src="/query/payroll-efficiency/chart.json"') < body.index("<h2>Results</h2>")
    assert 'id="plotly.js-style-global"' in body
    body = client.get("/query/payroll-efficiency?season=2015").get_data(as_text=True)
    assert 'data-chart-src="/query/payroll-efficiency/chart.json?season=2015"' in body


def test_gallery_lists_all_four_charts(client):
    body = client.get("/charts").get_data(as_text=True)
    for slug in ("top-woba-by-season", "payroll-efficiency", "aging-curves", "birth-cohort-war"):
        assert f'data-chart-src="/query/{slug}/chart.json"' in body
    assert 'href="/charts">Charts</a>' in body                 # nav link


def test_chart_hooks_are_validated_at_startup():
    saved = Q.load()
    Q.check_charts(saved, charts.QUERY_CHARTS)
    with pytest.raises(Q.QueryFileError, match="unknown chart builder"):
        Q.check_charts(saved, {})


# ---------------------------------------------------------------- season filter

def test_filter_counts_and_notice(app, client, test_db_path):
    result = run(app, test_db_path, "Q01")
    n = sum(1 for r in result.rows if r[0] == 2015)
    text = re.sub(r"\s+", " ", client.get("/query/top-woba-by-season?season=2015").get_data(as_text=True))
    assert f"Filtered to 2015 after the query ran: {n} of {result.row_count} rows." in text
    assert f'result-count">{n} rows' in text
    table = text.split("<tbody>")[1].split("</tbody>")[0]
    assert table.count("<tr>") == n and "2016" not in table


def test_filter_leaves_the_sql_unchanged(app, client):
    sql = html.escape(saved_by_id(app, "Q01").sql, quote=True)
    plain = client.get("/query/top-woba-by-season").get_data(as_text=True)
    filtered = client.get("/query/top-woba-by-season?season=2015").get_data(as_text=True)
    pre = re.compile(r'<pre class="sql"><code>(.*?)</code></pre>', re.S)
    assert pre.search(plain).group(1) == pre.search(filtered).group(1)
    assert html.unescape(pre.search(filtered).group(1)) == saved_by_id(app, "Q01").sql
    assert sql


def test_filter_applies_before_the_display_cap(client, monkeypatch):
    monkeypatch.setattr(Q, "MAX_DISPLAY_ROWS", 2)
    text = re.sub(r"\s+", " ", client.get("/query/top-woba-by-season?season=2015").get_data(as_text=True))
    assert "Showing the first 2 of" in text
    assert text.split("<tbody>")[1].split("</tbody>")[0].count("<tr>") == 2


@pytest.mark.parametrize("season", ["abc", "1999", "20 15"])
def test_filter_bad_season_is_400(client, season):
    assert client.get(f"/query/top-woba-by-season?season={season}").status_code == 400


def test_filter_form_only_where_a_season_column_exists(client):
    assert 'name="season"' in client.get("/query/top-woba-by-season").get_data(as_text=True)
    assert 'name="season"' not in client.get("/query/birth-cohort-war").get_data(as_text=True)
    assert client.get("/query/birth-cohort-war?season=2015").status_code == 400


def test_q18_season_is_its_target_not_a_filter(client):
    body = client.get(f"/query/comparable-hitters?player_id={HANK}&season=2015").get_data(as_text=True)
    assert "Filtered to" not in body and '<select id="season"' not in body


def test_filter_on_a_parameterized_query_keeps_the_player(client):
    body = client.get(f"/query/career-war-trajectory?player_id={HANK}&season=2016").get_data(as_text=True)
    assert f'<input type="hidden" name="player_id" value="{HANK}">' in body
    assert "Filtered to 2016 after the query ran: 1 of 4 rows." in re.sub(r"\s+", " ", body)


# ---------------------------------------------------------------- validation consistency

@pytest.mark.parametrize("url", [
    "/query/career-war-trajectory",
    "/query/career-war-trajectory?player_id=",
    "/query/comparable-hitters",
    "/query/comparable-hitters?player_id=",
    "/compare",
    "/compare?p1=",
])
def test_missing_id_shows_a_picker(client, url):
    resp = client.get(url)
    assert resp.status_code == 200
    assert 'name="q"' in resp.get_data(as_text=True)


@pytest.mark.parametrize("url", [
    "/query/career-war-trajectory?player_id=abc",
    "/query/career-war-trajectory?player_id=0",
    "/query/career-war-trajectory?player_id=-1",
    "/query/comparable-hitters?player_id=x1",
    "/query/comparable-hitters?player_id=0",
    f"/query/comparable-hitters?player_id={HANK}&season=abc",
    "/compare?p1=abc",
    "/compare?p1=0",
    f"/compare?p1={HANK}&p2=-2",
])
def test_invalid_id_is_400(client, url):
    assert client.get(url).status_code == 400


# ---------------------------------------------------------------- CSP

@pytest.mark.parametrize("url", ["/charts", "/team/TSA", "/query/payroll-efficiency",
                                 "/query/top-woba-by-season?season=2015", "/query/aging-curves"])
def test_csp_strict_on_chart_pages(client, url):
    resp = client.get(url)
    assert resp.status_code == 200
    assert resp.headers["Content-Security-Policy"] == CSP
    assert "unsafe" not in resp.headers["Content-Security-Policy"]
    body = resp.get_data(as_text=True)
    assert "<script>" not in body and "style=" not in body
