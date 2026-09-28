"""Saved queries: parser, registry checks, execution, and the /query routes."""
import re
import sqlite3

import pytest

from app import create_app
from app import queries as Q
from app.queries import PLAYER, SEASON, Entry, QueryFileError
from tests.conftest import REAL_DB

HANK, IVAN, MOE = 900010, 900011, 900015
ALL_IDS = ["Q01", "Q02", "Q03", "Q04", "Q05", "Q06", "Q07", "Q08", "Q09", "Q10", "Q11",
           "Q12a", "Q12b", "Q13", "Q14", "Q15", "Q16", "Q17", "Q18", "Q19", "Q20"]

RULER = "-- " + "=" * 40


def header(qid, title="A title", optional=False):
    return "\n".join([
        f"-- {qid}{' (optional)' if optional else ''}: {title}",
        "-- Business question: Why would",
        "--   anyone ask this?",
        "-- Technique: A join.",
        "-- Caveats: None",
        "--   at all.",
        "-- Verified: PASS.",
    ])


def sql_file(tmp_path, *blocks, tier="TIER 1: TEST TIER"):
    text = "\n".join([RULER, f"-- {tier}", RULER, ""] + [b + "\n" for b in blocks])
    path = tmp_path / "analysis.sql"
    path.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))   # CRLF, as on disk
    return path


# ---------------------------------------------------------------- parser: real file

def test_real_file_has_all_21_blocks():
    blocks = Q.parse_blocks(Q.QUERIES_FILE.read_text(encoding="utf-8"))
    assert [b.query_id for b in blocks] == ALL_IDS
    saved = Q.load()
    assert sorted(q.query_id for q in saved.values()) == sorted(ALL_IDS)


def test_real_file_tiers_suffixes_and_optional():
    saved = {q.query_id: q for q in Q.load().values()}
    assert saved["Q01"].tier.startswith("TIER 1:")
    assert saved["Q16"].tier.startswith("TIER 4:")
    assert saved["Q20"].tier == "ADDITIONAL"
    assert saved["Q12a"].title == "Pythagorean over/under-performers"
    assert saved["Q12b"].title.startswith("Does Pythagorean luck persist")
    assert saved["Q19"].optional and saved["Q19"].title.startswith("Is FIP a better predictor")
    assert not saved["Q18"].optional


def test_real_file_continuation_lines_and_params():
    saved = {q.query_id: q for q in Q.load().values()}
    assert "Stored WAR 2015–2025: 4.8" in saved["Q05"].verified
    assert saved["Q05"].example == {"target_player_id": 13611}
    assert saved["Q18"].example == {"target_player_id": 5361, "target_season": 2023}
    assert saved["Q18"].sql.startswith(
        "WITH params AS (SELECT ? AS target_player_id, ? AS target_season),\n")
    assert "Freddie Freeman" not in saved["Q18"].sql      # the CTE's comment went with it
    assert "Mookie Betts" not in saved["Q05"].sql
    for q in saved.values():
        assert Q.count_placeholders(q.sql) == len(q.params)
        assert q.sql.rstrip().endswith(";")


# ---------------------------------------------------------------- parser: temp files

def test_temp_file_parses_fields_suffixes_and_optional(tmp_path):
    path = sql_file(tmp_path,
                    header("Q01") + "\nSELECT 1 AS x;",
                    header("Q12a") + "\nSELECT 2 AS y;  -- trailing comment\n-- note after",
                    header("Q12b") + "\nWITH a AS (SELECT 3 AS z) SELECT z FROM a;",
                    header("Q19", "Optional one", optional=True) + "\nSELECT 4;")
    registry = {"one": Entry("Q01"), "two-a": Entry("Q12a"), "two-b": Entry("Q12b"), "opt": Entry("Q19")}
    saved = Q.load(path, registry)
    assert saved["one"].business_question == "Why would anyone ask this?"
    assert saved["one"].caveats == "None at all."
    assert saved["one"].tier == "TIER 1: TEST TIER"
    assert saved["two-a"].sql == "SELECT 2 AS y;"
    assert saved["opt"].optional and saved["opt"].title == "Optional one"
    assert "\r" not in saved["two-b"].sql


def test_missing_registry_entry_raises(tmp_path):
    path = sql_file(tmp_path, header("Q01") + "\nSELECT 1;", header("Q02") + "\nSELECT 2;")
    with pytest.raises(QueryFileError, match=r"not in the registry: \['Q02'\]"):
        Q.load(path, {"one": Entry("Q01")})


def test_extra_registry_entry_raises(tmp_path):
    path = sql_file(tmp_path, header("Q01") + "\nSELECT 1;")
    with pytest.raises(QueryFileError, match=r"registry ids not in analysis.sql: \['Q03'\]"):
        Q.load(path, {"one": Entry("Q01"), "three": Entry("Q03")})


def test_params_cte_is_bound_and_its_literals_become_the_example(tmp_path):
    path = sql_file(tmp_path, header("Q18") + "\n" + (
        "WITH params AS (SELECT 5361 AS target_player_id,   -- someone\n"
        "                       2023 AS target_season),\n"
        "x AS (SELECT target_player_id, target_season FROM params)\n"
        "SELECT * FROM x;"))
    saved = Q.load(path, {"comps": Entry("Q18", params=(PLAYER, SEASON))})["comps"]
    assert saved.sql.startswith("WITH params AS (SELECT ? AS target_player_id, ? AS target_season),\nx AS")
    assert saved.example == {"target_player_id": 5361, "target_season": 2023}
    assert saved.example_args == {"player_id": 5361, "season": 2023}
    assert sqlite3.connect(":memory:").execute(saved.sql, (7, 2020)).fetchall() == [(7, 2020)]


@pytest.mark.parametrize("cte, specs, match", [
    ("WITH params AS (SELECT 1 AS target_player_id),", (SEASON,), "names"),          # wrong name
    ("WITH params AS (SELECT 1 AS target_season, 2 AS target_player_id),",
     (PLAYER, SEASON), "names"),                                                    # wrong order
    ("WITH params AS (SELECT 1 AS target_player_id),", (PLAYER, SEASON), "names"),   # too few
    ("WITH params AS (SELECT 'x' AS target_player_id),", (PLAYER,), "is not int"),   # wrong type
    ("WITH params AS (SELECT abs(1) AS target_player_id),", (PLAYER,), "exactly one params CTE"),
    ("WITH params AS (SELECT 1 AS target_player_id),", (), "declares no params"),
])
def test_params_cte_mismatch_raises(tmp_path, cte, specs, match):
    path = sql_file(tmp_path, header("Q05") + f"\n{cte}\nx AS (SELECT 1 AS y) SELECT y FROM x;")
    with pytest.raises(QueryFileError, match=match):
        Q.load(path, {"q": Entry("Q05", params=specs)})


@pytest.mark.parametrize("sql, match", [
    ("SELECT 1; SELECT 2;", "more than one statement"),
    ("SELECT 1;\nDELETE FROM players;", "more than one statement"),
    ("DELETE FROM players;", "must start with WITH or SELECT"),
    ("PRAGMA foreign_keys = OFF;", "must start with WITH or SELECT"),
    ("SELECT 1", "no terminating semicolon"),
    ("SELECT 1;\nSELECT 2", "text after the final semicolon"),
    ("SELECT 'unterminated;", "not a complete SQL statement"),
])
def test_malformed_block_raises(tmp_path, sql, match):
    path = sql_file(tmp_path, header("Q01") + "\n" + sql)
    with pytest.raises(QueryFileError, match=match):
        Q.load(path, {"one": Entry("Q01")})


def test_app_refuses_to_start_on_a_bad_file(tmp_path, test_db_path):
    path = sql_file(tmp_path, header("Q01") + "\nSELECT 1; SELECT 2;")
    with pytest.raises(QueryFileError):
        create_app({"TESTING": True, "DATABASE": test_db_path, "SECRET_KEY": "x",
                    "QUERIES_FILE": path})


# ---------------------------------------------------------------- execution (fixture DB)

@pytest.mark.parametrize("query_id", ALL_IDS)
def test_every_query_executes_on_the_fixture(app, test_db_path, query_id):
    saved = next(q for q in app.extensions["saved_queries"].values() if q.query_id == query_id)
    conn = sqlite3.connect(test_db_path)
    try:
        result = Q.execute(conn, saved.sql, tuple(saved.example.values()))
    finally:
        conn.close()
    assert result.columns
    if query_id in ("Q03", "Q11"):
        assert result.row_count > 0            # fixture payroll is loaded


# ---------------------------------------------------------------- routes

def get(client, url, status=200):
    resp = client.get(url)
    assert resp.status_code == status, url
    return resp.get_data(as_text=True)


def test_index_groups_all_21_by_tier(app, client):
    body = get(client, "/query")
    for q in app.extensions["saved_queries"].values():
        assert f'href="/query/{q.slug}"' in body
    assert body.index("TIER 1:") < body.index("TIER 4:") < body.index("ADDITIONAL")
    assert 'href="/query">Saved queries</a>' in body          # nav link in base.html


@pytest.mark.parametrize("slug", [
    "nope",
    "Q01",
    "top-woba-by-season';--",
    "top-woba-by-season%3B%20DROP%20TABLE%20players",
    "%27%20OR%201%3D1%20--",
    "..%2F..%2Fapp%2F__init__.py",
    "SELECT%20*%20FROM%20players",
    "top-woba-by-season%22",
])
def test_unknown_slug_is_404(client, slug):
    body = get(client, "/query/" + slug, 404)
    assert "Traceback" not in body


def test_dot_dot_path_is_404(client):
    assert client.get("/query/../app/__init__.py").status_code == 404


def test_plain_query_shows_header_results_and_sql(client):
    body = get(client, "/query/top-woba-by-season")
    assert "Business question" in body and "Verified" in body
    assert "SQL executed" in body and "<pre class=\"sql\">" in body
    assert re.search(r'result-count">\d+ rows?', body)


def test_sql_pre_is_escaped(client):
    body = get(client, f"/query/comparable-hitters?player_id={HANK}&season=2015")
    assert "r.player_id &lt;&gt; t.player_id" in body
    assert "r.player_id <> t.player_id" not in body


def test_team_id_column_links_to_team_page(client):
    body = get(client, "/query/top-hr-by-season")
    assert 'href="/team/TSA">TSA</a>' in body


# Q05 ---------------------------------------------------------------------

def test_q05_without_player_shows_picker_and_example(client):
    body = get(client, "/query/career-war-trajectory")
    assert 'name="q"' in body
    assert 'href="/query/career-war-trajectory?player_id=13611">run the example</a>' in body
    assert "SQL executed" not in body


@pytest.mark.parametrize("player_id", ["0", "-5", ""])
def test_q05_non_positive_or_blank_player_shows_picker(client, player_id):
    body = get(client, f"/query/career-war-trajectory?player_id={player_id}")
    assert "Choose a player" in body and "SQL executed" not in body


def test_q05_picker_searches_and_links_by_id(client):
    body = get(client, "/query/career-war-trajectory?q=hank")
    assert f'href="/query/career-war-trajectory?player_id={HANK}">Hank Baseline</a>' in body


@pytest.mark.parametrize("player_id", ["abc", "1.5", "13611;DROP"])
def test_q05_non_integer_player_is_400(client, player_id):
    body = get(client, f"/query/career-war-trajectory?player_id={player_id}", 400)
    assert "player_id must be a whole number." in body


def test_q05_unknown_player_is_404(client):
    assert "There is no player with ID 999999." in get(
        client, "/query/career-war-trajectory?player_id=999999", 404)


def test_q05_valid_player_links_player_id_rows(client):
    body = get(client, f"/query/career-war-trajectory?player_id={HANK}")
    assert f'<a href="/player/{HANK}">Hank Baseline</a>' in body
    assert "4 rows" in body
    assert f"target_player_id</span> = <span class=\"mono\">{HANK}</span>" in body


# Q18 ---------------------------------------------------------------------

def test_q18_lists_qualified_seasons(client):
    body = get(client, f"/query/comparable-hitters?player_id={HANK}")
    seasons = re.findall(rf'player_id={HANK}&amp;season=(\d+)"', body)
    assert seasons == ["2015", "2016", "2017", "2020"]
    assert "SQL executed" not in body


@pytest.mark.parametrize("season, status", [("abc", 400), ("2019", 400), ("1900", 400)])
def test_q18_bad_season_is_400(client, season, status):
    get(client, f"/query/comparable-hitters?player_id={HANK}&season={season}", status)


def test_q18_unqualified_target_explains_instead_of_empty_table(client):
    body = get(client, f"/query/comparable-hitters?player_id={IVAN}&season=2016")
    assert "was not a qualified hitter in 2016" in body
    assert "Comps use qualified" in body
    assert "<table" not in body and "SQL executed" not in body


def test_q18_player_without_qualified_seasons(client):
    body = get(client, f"/query/comparable-hitters?player_id={MOE}")
    assert "has no qualified hitter-seasons" in body


def test_q18_runs_for_a_qualified_season(client):
    body = get(client, f"/query/comparable-hitters?player_id={HANK}&season=2015")
    assert "SQL executed" in body and "5 rows" in body
    assert f'href="/player/{HANK}"' not in body.split("<tbody>")[1]   # own seasons excluded


# payroll -----------------------------------------------------------------

def set_payroll_null(db_path, where="1 = 1"):
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("UPDATE team_stats SET payroll_usd = NULL WHERE " + where)
    conn.close()


@pytest.mark.parametrize("slug", ["payroll-efficiency", "team-cost-per-war"])
def test_payroll_panel_when_no_payroll(client, test_db_path, monkeypatch, slug):
    set_payroll_null(test_db_path)
    ran = []
    monkeypatch.setattr(Q, "execute", lambda *a: ran.append(a))
    body = get(client, f"/query/{slug}")
    assert "Payroll data not loaded" in body and "database/README.md" in body
    assert ran == []                                  # query not run


def test_partial_payroll_notice_shows_count(client, test_db_path):
    set_payroll_null(test_db_path, "team_id = 'TSB' AND season_year = 2020")
    body = get(client, "/query/payroll-efficiency")
    assert "Payroll loaded for 7 of 8 team-seasons" in body
    assert "SQL executed" in body


def test_full_payroll_shows_no_notice(client):
    body = get(client, "/query/team-cost-per-war")
    assert "Payroll loaded for" not in body and "Payroll data not loaded" not in body


# no request-built SQL ----------------------------------------------------

def test_execute_only_ever_receives_registry_sql(app, client, monkeypatch):
    registry_sql = {q.sql for q in app.extensions["saved_queries"].values()}
    seen = []
    real = Q.execute

    def spy(db, sql, params=()):
        seen.append(sql)
        assert sql in registry_sql
        return real(db, sql, params)

    monkeypatch.setattr(Q, "execute", spy)
    urls = [f"/query/{q.slug}" for q in app.extensions["saved_queries"].values()] + [
        f"/query/career-war-trajectory?player_id={HANK}&q=x' OR 1=1",
        f"/query/comparable-hitters?player_id={HANK}&season=2015&extra=;DROP TABLE players",
        "/query/top-woba-by-season?sql=SELECT 1",
    ]
    for url in urls:
        client.get(url)
    assert len(seen) == 22        # 19 plain + Q05 + Q18, plus Q01 again with ?sql=


# player page links ---------------------------------------------------------

def test_player_page_links_q05_and_q18(client):
    body = get(client, f"/player/{HANK}")
    assert f'href="/query/career-war-trajectory?player_id={HANK}"' in body
    assert f'href="/query/comparable-hitters?player_id={HANK}"' in body
    assert f'href="/query/comparable-hitters?player_id={HANK}&amp;season=2015"' in body


def test_pitcher_page_has_q05_but_no_q18(client):
    body = get(client, f"/player/{MOE}")
    assert "/query/career-war-trajectory?player_id=" in body
    assert "/query/comparable-hitters" not in body


# ---------------------------------------------------------------- real DB

# Row counts from queries/VERIFY.md, section 5 (Per-query results).
VERIFY_ROW_COUNTS = {
    "Q01": 110, "Q02": 330, "Q03": 330, "Q04": 114, "Q05": 11, "Q06": 30, "Q07": 2542,
    "Q08": 72, "Q09": 116, "Q10": 24, "Q11": 329, "Q12a": 20, "Q12b": 3, "Q13": 8,
    "Q14": 66, "Q15": 25, "Q16": 48, "Q17": 25, "Q18": 5, "Q19": 3, "Q20": 121,
}


@pytest.mark.skipif(not REAL_DB.is_file(), reason="database/baseball.db not built")
def test_real_db_row_counts_match_verify_md():
    conn = sqlite3.connect(f"file:{REAL_DB.as_posix()}?mode=ro", uri=True)
    try:
        payroll = conn.execute("SELECT COUNT(payroll_usd) FROM team_stats").fetchone()[0]
        counts = {}
        for q in Q.load().values():
            if q.requires_payroll and payroll == 0:
                continue                  # payroll.csv is optional and untracked
            counts[q.query_id] = Q.execute(conn, q.sql, tuple(q.example.values())).row_count
    finally:
        conn.close()
    assert counts == {k: v for k, v in VERIFY_ROW_COUNTS.items() if k in counts}
    assert len(counts) >= 19
