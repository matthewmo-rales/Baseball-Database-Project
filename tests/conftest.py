"""Fixtures: an app pointed at a throwaway DB built from design/schema.sql.

All rows are fictional (IDs in the 900000s) so no test depends on, or
reproduces, FanGraphs data.
"""
import re
import shutil
import sqlite3
from pathlib import Path

import pytest

from app import create_app

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "design" / "schema.sql"
REAL_DB = ROOT / "database" / "baseball.db"

SEASONS = [(2015, 162, 0), (2016, 162, 0), (2017, 162, 0), (2020, 60, 1)]

# (player_id, full_name, birth_date, primary_position)
PLAYERS = [
    (900001, "Testy McFakerson", "1990-04-01", "SS"),
    (900002, "Testy McFakerson", "1996-11-15", "P"),
    (900003, "Zoë Fictíciá", "1993-06-30", "OF"),
    (900004, "Zed 90% Fictional", None, None),
    (900005, "Zed 900 Fictional", None, None),
    (900006, "Zed Q_Fictional", None, "C"),
    (900007, "Zed QxFictional", None, "C"),
]

# multi-team rows (team_id NULL) keep the fixture free of teams/divisions
BATTING = [  # (player_id, season_year, plate_appearances)
    (900001, 2015, 400),
    (900001, 2016, 500),
    (900002, 2017, 0),  # pitcher's 0-PA batting row
    (900003, 2016, 300),
]
PITCHING = [  # (player_id, season_year, outs_recorded)
    (900001, 2017, 3),  # position player mops up: pushes last season to 2017
    (900002, 2016, 540),
    (900002, 2017, 600),
]


# ---------------------------------------------------------------- stat-page fixtures
# Fictional players with full stat lines for the player, season, compare and
# chart tests. Qualified = PA >= 3.1 * games (503 in 162, 186 in 60) and
# outs >= 3 * games (486 in 162, 180 in 60).
# Inserted out of display order, so /teams must sort AL before NL and
# East, Central, West within a league. TSC-TSG have no stat rows.
DIVISIONS = [("ALE", "East", "AL"), ("NLC", "Central", "NL"), ("ALW", "West", "AL"), ("ALC", "Central", "AL")]
TEAMS = [  # (team_id, team_name, city, division_id, fangraphs_abbrev)
    ("TSA", "Fixture Alphas", "Mocktown", "ALE", "TSA"),
    ("TSB", "Fixture Betas", "Mocktown", "ALE", "TSB"),          # shares a city with TSA
    ("TSD", "Fixture 500 Club", "Fivehundred", "ALW", "TSD"),
    ("TSC", "Fixture 50% Club", "Percent Falls", "ALW", "TSC"),  # literal '%'
    ("TSF", "Fixture QxStars", "Lettertown", "ALC", "TSF"),
    ("TSE", "Fixture Q_Stars", "Underscore Bay", "ALC", "TSE"),  # literal '_'
    ("TSG", "Fixture Gammas", "Tsarville", "NLC", "TSG"),        # city contains 'tsa' (TSA's id)
]

# (player_id, full_name, birth_date, primary_position, bats, throws, debut_year)
STAT_PLAYERS = [
    (900010, "Hank Baseline", "1991-05-05", "SS", "R", "R", 2014),
    (900011, "Ivan Rangefactor", "1992-03-03", "SS", "L", "R", 2015),
    (900012, "Jules Doubleplay", "1990-01-01", "SS", "B", "R", None),
    (900013, "Kurt Slugwell", "1989-02-02", "DH", "R", "R", 2012),
    (900014, "Lou Nowhere", None, None, None, None, None),
    (900015, "Moe Innings", "1988-08-08", "P", "R", "R", 2013),
    (900016, "Ned Setup", "1993-09-09", "P", "L", "L", 2015),
    (900017, "Otto Bothways", "1995-07-05", "DH", "L", "R", 2015),
    # Filler shortstops and starters, so baselines have enough "others".
    (900020, "Abe Fielder", "1994-01-01", "SS", "R", "R", 2015),
    (900021, "Ben Fielder", "1994-01-02", "SS", "R", "R", 2015),
    (900022, "Cal Fielder", "1994-01-03", "SS", "R", "R", 2015),
    (900023, "Dan Fielder", "1994-01-04", "SS", "R", "R", 2015),
    (900030, "Eli Armstrong", "1992-02-01", "P", "R", "R", 2015),
    (900031, "Fox Armstrong", "1992-02-02", "P", "R", "R", 2015),
    (900032, "Gus Armstrong", "1992-02-03", "P", "R", "R", 2015),
    (900033, "Hal Armstrong", "1992-02-04", "P", "R", "R", 2015),
    (900034, "Ike Armstrong", "1992-02-05", "P", "R", "R", 2015),
]


def _filler_bat(pid, year, pa, war):
    """A qualified-looking but unremarkable SS line (low wOBA/wRC+)."""
    ab = pa - 50
    return (pid, year, "TSB", 0, 140, pa, ab, ab // 4, 20, 1, 8, 60, 55, 45, 1, 3, 110, 2, 0,
            3, 1, .300, 90, war, -5.0, 3.0, 0.0)


def _filler_pitch(pid, war):
    """A qualified 2016 starter, worse than Moe on ERA-, FIP and WAR."""
    return (pid, 2016, "TSB", 0, 30, 30, 9, 11, 0, 510, 720, 175, 80, 75, 22, 55, 1, 4, 150,
            4.40, 4.30, 110, 108, war, 0.70, 0.300)

BATTING_COLS = (
    "player_id, season_year, team_id, is_multi_team, games, plate_appearances, at_bats, hits,"
    " doubles, triples, home_runs, runs, rbi, walks, intentional_walks, hit_by_pitch, strikeouts,"
    " sac_flies, sac_hits, stolen_bases, caught_stealing, woba, wrc_plus, war, off_runs, def_runs, bsr"
)
STAT_BATTING = [
    # Hank Baseline, SS: qualified 2015/16/20, multi-team 2017.
    # Totals: AB 1800, H 506, BB 165, HBP 17, SF 18, 2B 93, 3B 6, HR 71.
    (900010, 2015, "TSA", 0, 150, 600, 540, 162, 30, 3, 20, 90, 80, 50, 2, 5, 100, 5, 0, 10, 3, .350, 120, 4.0, 10.0, 5.0, 1.0),
    (900010, 2016, "TSA", 0, 155, 650, 580, 150, 25, 2, 25, 85, 90, 60, 3, 5, 120, 5, 0, 8, 2, .340, 115, 3.0, 8.0, 4.0, 0.5),
    (900010, 2017, None, 1, 140, 550, 500, 140, 28, 1, 18, 70, 75, 40, 1, 5, 90, 5, 0, 6, 2, .330, 110, 2.5, 5.0, 3.0, 0.0),
    (900010, 2020, "TSB", 0, 50, 200, 180, 54, 10, 0, 8, 30, 28, 15, 0, 2, 40, 3, 0, 2, 1, .360, 125, 1.5, 4.0, 1.0, 0.2),
    # Ivan Rangefactor, SS: qualified 2015 only.
    (900011, 2015, "TSA", 0, 155, 620, 560, 160, 32, 2, 15, 80, 70, 50, 1, 5, 110, 5, 0, 5, 2, .330, 105, 2.0, 3.0, 4.0, 0.0),
    (900011, 2016, "TSB", 0, 80, 300, 270, 70, 12, 1, 6, 30, 25, 25, 0, 2, 60, 3, 0, 2, 1, .300, 90, 0.5, -2.0, 2.0, 0.0),
    (900011, 2020, "TSB", 0, 30, 100, 90, 20, 4, 0, 2, 10, 8, 8, 0, 1, 20, 1, 0, 0, 0, .280, 75, -0.1, -2.0, 1.0, 0.0),
    # Jules Doubleplay, SS: qualified 2015-16, no 2020.
    (900012, 2015, "TSA", 0, 150, 580, 520, 150, 28, 4, 22, 85, 85, 50, 2, 5, 95, 5, 0, 12, 4, .370, 135, 5.0, 15.0, 5.0, 2.0),
    (900012, 2016, "TSA", 0, 158, 610, 550, 165, 33, 3, 24, 95, 95, 52, 2, 4, 100, 4, 0, 10, 3, .360, 130, 4.5, 12.0, 5.0, 1.0),
    # Kurt Slugwell, DH: qualified 2015.
    (900013, 2015, "TSA", 0, 150, 600, 530, 150, 30, 1, 35, 90, 100, 60, 5, 5, 140, 5, 0, 0, 0, .400, 150, 3.5, 25.0, -10.0, -1.0),
    (900013, 2017, "TSA", 0, 140, 560, 500, 130, 25, 1, 30, 80, 90, 55, 4, 5, 130, 0, 0, 0, 0, .380, 140, 3.0, 20.0, -9.0, -1.0),
    # Lou Nowhere, no position.
    (900014, 2016, "TSB", 0, 20, 50, 45, 10, 2, 0, 1, 5, 4, 4, 0, 0, 10, 1, 0, 0, 0, .290, 80, 0.1, 0.0, 0.0, 0.0),
    # Otto Bothways, DH and pitcher: qualified hitter 2015-16.
    (900017, 2015, "TSA", 0, 130, 520, 470, 130, 25, 2, 25, 75, 80, 45, 4, 3, 120, 2, 0, 10, 2, .345, 120, 2.0, 12.0, -8.0, 1.0),
    (900017, 2016, "TSA", 0, 120, 450, 400, 110, 20, 1, 22, 60, 70, 45, 3, 3, 110, 2, 0, 8, 1, .355, 125, 2.5, 12.0, -8.0, 0.5),
    # Lou Nowhere, 2015: 0 PA, no pitching row, small nonzero WAR (a defensive
    # or pinch-running appearance). FanGraphs stores wOBA 0 on such rows.
    (900014, 2015, "TSB", 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, None, 0.02, 0.0, 0.2, 0.0),
    # Filler SS. Qualified SS per season: 2015 = Hank, Ivan, Jules + 4 (7);
    # 2016 = Hank, Jules + 4 (6); 2020 = Hank + 4 (5).
    *[_filler_bat(pid, 2015, 560, war) for pid, war in zip(range(900020, 900024), (1.0, 2.0, 3.0, 3.0))],
    *[_filler_bat(pid, 2016, 560, war) for pid, war in zip(range(900020, 900024), (2.0, 2.0, 1.0, 1.5))],
    *[_filler_bat(pid, 2020, 200, 0.5) for pid in range(900020, 900024)],
]

PITCHING_COLS = (
    "player_id, season_year, team_id, is_multi_team, games, games_started, wins, losses, saves,"
    " outs_recorded, batters_faced, hits_allowed, runs_allowed, earned_runs, home_runs_allowed,"
    " walks, intentional_walks, hit_batters, strikeouts, fip, xfip, era_minus, fip_minus, war,"
    " lob_pct, babip_against"
)
STAT_PITCHING = [
    # Moe Innings, P: qualified 2015/16/20. Totals: outs 1320, ER 150, H 405, BB 110, K 440.
    (900015, 2015, "TSA", 0, 32, 32, 15, 8, 0, 600, 820, 180, 75, 70, 20, 50, 2, 5, 200, 3.40, 3.60, 85, 88, 4.0, 0.75, 0.290),
    (900015, 2016, "TSA", 0, 30, 30, 12, 10, 0, 540, 740, 170, 65, 60, 18, 45, 1, 4, 180, 3.50, 3.70, 90, 92, 3.2, 0.74, 0.295),
    (900015, 2020, "TSB", 0, 12, 12, 5, 3, 0, 180, 250, 55, 22, 20, 6, 15, 0, 1, 60, 3.30, 3.50, 80, 85, 1.4, 0.76, 0.285),
    # Ned Setup, P: unqualified 2015 (200 outs), qualified 2016.
    (900016, 2015, "TSA", 0, 60, 0, 4, 3, 20, 200, 270, 50, 20, 18, 5, 20, 2, 1, 80, 2.90, 3.10, 70, 75, 1.2, 0.80, 0.280),
    (900016, 2016, "TSB", 0, 25, 25, 8, 9, 0, 500, 700, 160, 70, 65, 20, 50, 1, 3, 140, 4.20, 4.10, 105, 102, 1.5, 0.70, 0.300),
    # Otto Bothways: unqualified 2015 (360 outs), qualified 2016 (490).
    (900017, 2015, "TSA", 0, 20, 20, 8, 5, 0, 360, 480, 90, 40, 36, 10, 35, 0, 2, 130, 3.60, 3.80, 92, 95, 2.2, 0.73, 0.285),
    (900017, 2016, "TSA", 0, 25, 25, 10, 6, 0, 490, 650, 120, 50, 45, 12, 40, 0, 3, 170, 3.30, 3.40, 88, 86, 3.0, 0.75, 0.280),
    # Filler starters (listed P), qualified 2016. Qualified pitchers listed at P
    # in 2016: Moe, Ned + 5 (7); Otto (DH) qualifies but is not P.
    *[_filler_pitch(pid, war) for pid, war in zip(range(900030, 900035), (2.0, 2.0, 3.0, 1.0, 2.0))],
]


# Fictional cohort players so Q10 and Q16 return rows: 25 OF born 1990 and 15 C
# born 1991, each with unqualified 300-PA seasons for TSB in 2015 and 2016.
# Q10: the 1990 cohort has 26 players (these 25 + Jules). Q16: 25 OF pairs
# into age 26 and 15 C pairs into age 25 (its minimum is 15 pairs).
COHORT_PLAYERS = (
    [(900200 + i, f"Cohort Outfielder {i:02d}", "1990-03-01", "OF", "R", "R", 2014) for i in range(25)]
    + [(900230 + i, f"Cohort Catcher {i:02d}", "1991-03-01", "C", "R", "R", 2014) for i in range(15)]
)


def _cohort_bat(pid, year, i):
    wrc = 95 + i + (3 if year == 2016 else 0) - (i % 4)
    return (pid, year, "TSB", 0, 90, 300, 270, 70, 12, 1, 6, 30, 28, 25, 0, 2, 60, 3, 0, 2, 1,
            .310, wrc, round(0.2 + 0.05 * i, 2), 0.0, 0.0, 0.0)


COHORT_BATTING = [_cohort_bat(pid, year, i) for i, (pid, *_rest) in enumerate(COHORT_PLAYERS)
                  for year in (2015, 2016)]

# Fictional team-seasons with payroll, so Q03 and Q11 have data (8 rows).
TEAM_STATS_COLS = ("team_id, season_year, games_played, wins, losses, runs_scored, runs_allowed,"
                   " payroll_usd")
TEAM_STATS = [
    ("TSA", 2015, 162, 90, 72, 750, 650, 150_000_000),
    ("TSB", 2015, 162, 72, 90, 650, 750, 90_000_000),
    ("TSA", 2016, 162, 85, 77, 720, 680, 160_000_000),
    ("TSB", 2016, 162, 77, 85, 680, 720, 95_000_000),
    ("TSA", 2017, 162, 80, 82, 700, 700, 170_000_000),
    ("TSB", 2017, 162, 82, 80, 700, 700, 100_000_000),
    ("TSA", 2020, 60, 35, 25, 280, 240, 60_000_000),
    ("TSB", 2020, 60, 25, 35, 240, 280, 40_000_000),
]


def _insert(conn, table, cols, rows):
    marks = ", ".join("?" * len(rows[0]))
    conn.executemany(f"INSERT INTO {table} ({cols}) VALUES ({marks})", rows)


def build_test_db(path):
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.executemany(
            "INSERT INTO seasons (season_year, scheduled_games, is_shortened) VALUES (?, ?, ?)",
            SEASONS,
        )
        conn.executemany(
            "INSERT INTO players (player_id, full_name, birth_date, primary_position) VALUES (?, ?, ?, ?)",
            PLAYERS,
        )
        conn.executemany(
            "INSERT INTO batting_stats (player_id, season_year, team_id, is_multi_team, plate_appearances)"
            " VALUES (?, ?, NULL, 1, ?)",
            BATTING,
        )
        conn.executemany(
            "INSERT INTO pitching_stats (player_id, season_year, team_id, is_multi_team, outs_recorded)"
            " VALUES (?, ?, NULL, 1, ?)",
            PITCHING,
        )
        _insert(conn, "divisions", "division_id, division_name, league", DIVISIONS)
        _insert(conn, "teams", "team_id, team_name, city, division_id, fangraphs_abbrev", TEAMS)
        _insert(conn, "players",
                "player_id, full_name, birth_date, primary_position, bats, throws, debut_year",
                STAT_PLAYERS)
        _insert(conn, "batting_stats", BATTING_COLS, STAT_BATTING)
        _insert(conn, "pitching_stats", PITCHING_COLS, STAT_PITCHING)
        _insert(conn, "team_stats", TEAM_STATS_COLS, TEAM_STATS)
        _insert(conn, "players",
                "player_id, full_name, birth_date, primary_position, bats, throws, debut_year",
                COHORT_PLAYERS)
        _insert(conn, "batting_stats", BATTING_COLS, COHORT_BATTING)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="session")
def template_db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "template.db"
    build_test_db(path)
    return path


@pytest.fixture
def test_db_path(template_db_path, tmp_path):
    """A fresh copy per test, since the notes tests write to it."""
    path = tmp_path / "test.db"
    shutil.copyfile(template_db_path, path)
    return path


def csrf_token(client, url):
    """GET a form page and pull the CSRF token out of its hidden input."""
    body = client.get(url).get_data(as_text=True)
    match = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', body) or \
        re.search(r'name="csrf_token" value="([^"]+)"', body)
    assert match, "no CSRF token on " + url
    return match.group(1)


def query_db(path, sql, params=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, params).fetchall()
    finally:
        conn.close()


@pytest.fixture
def app(test_db_path):
    return create_app({
        "TESTING": True,
        "DATABASE": test_db_path,
        "SECRET_KEY": "test-only-not-secret",
    })


@pytest.fixture
def client(app):
    return app.test_client()
