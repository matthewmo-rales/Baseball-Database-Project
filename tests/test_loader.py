"""Loader: notes carry-over and the atomic tmp-build-then-swap.

The load steps that need the FanGraphs/Chadwick cache are stubbed; schema.sql
and seed_reference.sql run for real, so the tmp DB has the real structure.
"""
import importlib.util
import json
import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from tests.conftest import ROOT, SEASONS, query_db

spec = importlib.util.spec_from_file_location("load_data", ROOT / "scripts" / "load_data.py")
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)

NOTES = [
    # (note_id, player_id, category, body, created_at, updated_at)
    (3, 900001, "hitting", "Keeps his hands back.", "2026-01-02T03:04:05Z", None),
    (7, 900003, "general", "Multi\nline", "2026-02-03T04:05:06Z", "2026-02-04T00:00:00Z"),
    (9, 900002, "pitching", "Orphan-to-be.", "2026-03-04T05:06:07Z", None),
]


def seed_notes(db_path, seq=None):
    """Insert NOTES; optionally raise the AUTOINCREMENT high-water mark to `seq`,
    as if newer notes had been created and then deleted."""
    conn = sqlite3.connect(db_path)
    with conn:
        conn.executemany("INSERT INTO player_notes VALUES (?, ?, ?, ?, ?, ?)", NOTES)
        if seq is not None:
            conn.execute("UPDATE sqlite_sequence SET seq = ? WHERE name = 'player_notes'", (seq,))
    conn.close()


def fresh_build(path, player_ids):
    """A new DB from schema.sql with just these players, as the loader would have."""
    conn = loader.connect(path)
    loader.run_sql_file(conn, loader.SCHEMA_SQL)
    with conn:
        conn.executemany("INSERT INTO seasons (season_year, scheduled_games) VALUES (?, ?)",
                         [(y, g) for y, g, _ in SEASONS])
        conn.executemany("INSERT INTO players (player_id, full_name) VALUES (?, ?)",
                         [(pid, f"Player {pid}") for pid in player_ids])
    return conn


def next_note_id(conn):
    with conn:
        return conn.execute(
            "INSERT INTO player_notes (player_id, body) VALUES (900001, 'new') RETURNING note_id"
        ).fetchone()[0]


def as_dict(row):
    return dict(zip(("note_id", "player_id", "category", "body", "created_at", "updated_at"), row))


# ---------------------------------------------------------------- read / restore

def test_read_notes_missing_db_or_table(tmp_path):
    assert loader.read_notes(tmp_path / "nope.db") == ([], 0)
    bare = tmp_path / "bare.db"
    sqlite3.connect(bare).close()
    assert loader.read_notes(bare) == ([], 0)


def test_read_notes_without_sqlite_sequence(tmp_path):
    """A DB from before note_id was AUTOINCREMENT has no sqlite_sequence."""
    old = tmp_path / "old.db"
    conn = sqlite3.connect(old)
    with conn:
        conn.execute("CREATE TABLE player_notes (note_id INTEGER PRIMARY KEY, player_id INTEGER, "
                     "category TEXT, body TEXT, created_at TEXT, updated_at TEXT)")
        conn.execute("INSERT INTO player_notes VALUES (1, 900001, 'general', 'x', '2026-01-01T00:00:00Z', NULL)")
    conn.close()
    rows, seq = loader.read_notes(old)
    assert [r["note_id"] for r in rows] == [1]
    assert seq == 0


def test_restore_round_trip_with_orphan(test_db_path, tmp_path):
    seed_notes(test_db_path)
    rows, seq = loader.read_notes(test_db_path)
    assert rows == [as_dict(n) for n in NOTES]
    assert seq == 9                                  # explicit-id inserts raise the sequence

    # New build: player 900002 is gone from the data.
    conn = fresh_build(tmp_path / "new.db", [900001, 900003])
    orphans = loader.restore_notes(conn, rows, seq)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()

    assert orphans == [as_dict(NOTES[2])]
    assert query_db(tmp_path / "new.db", "SELECT * FROM player_notes ORDER BY note_id") == NOTES[:2]


def test_orphaned_note_id_is_not_reused_after_restore(test_db_path, tmp_path):
    # Note 9 is the newest and becomes an orphan; its id must stay retired,
    # or the orphans file and the DB would each have a different "note 9".
    seed_notes(test_db_path)
    rows, seq = loader.read_notes(test_db_path)
    conn = fresh_build(tmp_path / "new.db", [900001, 900003])
    loader.restore_notes(conn, rows, seq)
    assert next_note_id(conn) == 10
    conn.close()


def test_old_sequence_above_max_note_id_carries_over(test_db_path, tmp_path):
    seed_notes(test_db_path, seq=20)                 # notes 10..20 were created, then deleted
    rows, seq = loader.read_notes(test_db_path)
    assert seq == 20
    conn = fresh_build(tmp_path / "new.db", [900001, 900002, 900003])
    loader.restore_notes(conn, rows, seq)
    assert query_db(tmp_path / "new.db", "SELECT seq FROM sqlite_sequence WHERE name = 'player_notes'") == [(20,)]
    assert next_note_id(conn) == 21
    conn.close()


def test_sequence_carries_over_even_with_no_notes_left(tmp_path):
    # Every note deleted before the rebuild: no rows to restore, and the new
    # table has no sqlite_sequence row yet, so restore_notes must insert one.
    conn = fresh_build(tmp_path / "new.db", [900001])
    loader.restore_notes(conn, [], 12)
    assert next_note_id(conn) == 13
    conn.close()


def test_restore_never_lowers_the_sequence(tmp_path):
    conn = fresh_build(tmp_path / "new.db", [900001])
    loader.restore_notes(conn, [as_dict(NOTES[0]) | {"note_id": 50}], 5)
    assert next_note_id(conn) == 51
    conn.close()


def test_save_orphans_appends_without_duplicates(tmp_path):
    path = tmp_path / "orphans.json"
    a, b = as_dict(NOTES[0]), as_dict(NOTES[2])
    assert loader.save_orphans(path, [a]) == 1
    assert loader.save_orphans(path, [a, b]) == 2       # a from an earlier run is kept once
    assert json.loads(path.read_text(encoding="utf-8")) == [a, b]


# ---------------------------------------------------------------- main(): atomic swap

@pytest.fixture
def fake_cache(tmp_path):
    """Empty cache files so main()'s missing-cache pre-check passes."""
    cache = tmp_path / "raw"
    cache.mkdir()
    for name in loader.missing_fangraphs_cache(cache):
        (cache / name).touch()
    return cache


@pytest.fixture
def stub_steps(monkeypatch):
    """Replace the data steps: load two of the three fixture players, skip the rest."""
    def fake_load_stats(conn, kind, cache_dir, refresh):
        if kind == "batting":
            with conn:
                conn.executemany("INSERT INTO players (player_id, full_name) VALUES (?, ?)",
                                 [(900001, "Testy McFakerson"), (900003, "Zoë Fictíciá")])
        return pd.DataFrame()

    monkeypatch.setattr(loader, "load_stats", fake_load_stats)
    monkeypatch.setattr(loader, "load_chadwick", lambda *a: None)
    monkeypatch.setattr(loader, "load_payroll", lambda *a, **k: True)
    monkeypatch.setattr(loader, "load_team_results", lambda *a: None)
    monkeypatch.setattr(loader, "validate",
                        lambda conn, *a: len(conn.execute("PRAGMA foreign_key_check").fetchall()))


def run_main(db, cache):
    return loader.main(["--db", str(db), "--cache-dir", str(cache)])


def test_successful_rebuild_swaps_and_keeps_notes(test_db_path, fake_cache, stub_steps, capsys):
    seed_notes(test_db_path, seq=20)
    assert run_main(test_db_path, fake_cache) == 0

    assert query_db(test_db_path, "SELECT * FROM player_notes ORDER BY note_id") == NOTES[:2]
    assert query_db(test_db_path, "SELECT COUNT(*) FROM players")[0][0] == 2
    assert not test_db_path.with_name(test_db_path.name + ".tmp").exists()

    orphan_file = test_db_path.with_name(loader.ORPHANS_NAME)
    assert json.loads(orphan_file.read_text(encoding="utf-8")) == [as_dict(NOTES[2])]
    assert "1 note(s) reference players no longer in the data" in capsys.readouterr().out

    # Through the real main(): the old sequence (20) survives the swap.
    conn = sqlite3.connect(test_db_path)
    assert next_note_id(conn) == 21
    conn.close()


def test_leftover_tmp_is_replaced(test_db_path, fake_cache, stub_steps):
    tmp = test_db_path.with_name(test_db_path.name + ".tmp")
    tmp.write_bytes(b"junk from a crashed run")
    tmp.with_name(tmp.name + "-journal").write_bytes(b"stale journal")
    assert run_main(test_db_path, fake_cache) == 0
    assert not tmp.exists()


@pytest.mark.parametrize("error", [loader.LoadError("injected"), sqlite3.OperationalError("injected")])
def test_failure_mid_load_leaves_original_byte_identical(test_db_path, fake_cache, stub_steps,
                                                         monkeypatch, capsys, error):
    seed_notes(test_db_path)
    before = test_db_path.read_bytes()
    swaps = []
    monkeypatch.setattr(loader.os, "replace", lambda *a: swaps.append(a))

    def boom(*a):
        raise error
    monkeypatch.setattr(loader, "load_chadwick", boom)

    assert run_main(test_db_path, fake_cache) == 1
    assert test_db_path.read_bytes() == before
    assert swaps == []
    err = capsys.readouterr().err
    assert "LOAD FAILED at step [5/9 identity]" in err
    assert "was not changed" in err
    assert "Traceback" not in err


def test_validation_failure_does_not_swap(test_db_path, fake_cache, stub_steps, monkeypatch, capsys):
    seed_notes(test_db_path)
    before = test_db_path.read_bytes()
    monkeypatch.setattr(loader, "validate", lambda *a: 3)
    assert run_main(test_db_path, fake_cache) == 1
    assert test_db_path.read_bytes() == before
    assert "VALIDATION FAILED" in capsys.readouterr().err


def test_swap_permission_error_is_friendly_and_keeps_original(test_db_path, fake_cache, stub_steps,
                                                               monkeypatch, capsys):
    seed_notes(test_db_path)
    before = test_db_path.read_bytes()

    real_replace = loader.os.replace

    def locked(src, dst):
        if Path(dst) == test_db_path:      # only the DB swap; orphan-file writes still work
            raise PermissionError(32, "The process cannot access the file because it is being used")
        return real_replace(src, dst)
    monkeypatch.setattr(loader.os, "replace", locked)

    assert run_main(test_db_path, fake_cache) == 1
    assert test_db_path.read_bytes() == before
    tmp = test_db_path.with_name(test_db_path.name + ".tmp")
    assert tmp.exists()                                   # kept for inspection
    err = capsys.readouterr().err
    assert "is open in another program" in err
    assert "Close it and run the loader again" in err
    assert "Traceback" not in err
