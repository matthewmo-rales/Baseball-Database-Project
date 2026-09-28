"""Fixtures: an app pointed at a throwaway DB built from design/schema.sql.

All rows are fictional (IDs in the 900000s) so no test depends on, or
reproduces, FanGraphs data.
"""
import sqlite3
from pathlib import Path

import pytest

from app import create_app

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "design" / "schema.sql"
REAL_DB = ROOT / "database" / "baseball.db"

SEASONS = [(2015, 162, 0), (2016, 162, 0), (2017, 162, 0)]

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
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="session")
def test_db_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("db") / "test.db"
    build_test_db(path)
    return path


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
