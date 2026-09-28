import re
import sqlite3
from pathlib import Path

import pytest

from app import CSP, create_app
from app.db import get_ro_db

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
TRACEBACK_MARKERS = ("Traceback", 'File "', "sqlite3.", "Werkzeug Debugger")


def test_sql_injection_attempt_returns_no_rows(client):
    resp = client.get("/", query_string={"q": "' OR 1=1 --"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "No players match" in body
    assert '<a href="/player/' not in body


def test_ro_connection_rejects_writes(app):
    with app.app_context():
        conn = get_ro_db()
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(
                "INSERT INTO seasons (season_year, scheduled_games) VALUES (?, ?)",
                (2099, 162),
            )


def test_ro_connection_has_foreign_keys_on(app):
    with app.app_context():
        assert get_ro_db().execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_unknown_url_renders_custom_404(client):
    resp = client.get("/no/such/page")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 404
    assert "Page not found" in body
    assert "Back to player search" in body
    for marker in TRACEBACK_MARKERS:
        assert marker not in body


def test_500_is_friendly_and_logged(test_db_path, caplog):
    app = create_app({
        "TESTING": True,
        "PROPAGATE_EXCEPTIONS": False,
        "DATABASE": test_db_path,
        "SECRET_KEY": "test-only-not-secret",
    })

    @app.route("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    resp = app.test_client().get("/boom")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 500
    assert "Something went wrong" in body
    assert "secret internal detail" not in body
    for marker in TRACEBACK_MARKERS:
        assert marker not in body
    assert "secret internal detail" in caplog.text


def test_missing_database_renders_setup_page(tmp_path):
    app = create_app({
        "TESTING": True,
        "DATABASE": tmp_path / "absent.db",
        "SECRET_KEY": "test-only-not-secret",
    })
    resp = app.test_client().get("/", query_string={"q": "smith"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 503
    assert "python scripts/load_data.py" in body
    assert "Traceback" not in body
    assert not (tmp_path / "absent.db").exists()  # mode=ro never creates it


@pytest.mark.parametrize("path", ["/", "/?q=smith", "/no/such/page"])
def test_security_headers_present(client, path):
    resp = client.get(path)
    assert resp.headers["Content-Security-Policy"] == CSP
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "same-origin"


def test_csp_is_strict():
    assert "'unsafe-inline'" not in CSP
    assert "'unsafe-eval'" not in CSP
    assert "script-src 'self';" in CSP
    assert "style-src 'self';" in CSP


def test_output_is_autoescaped(client):
    body = client.get("/", query_string={"q": "<script>x"}).get_data(as_text=True)
    assert "<script>x" not in body
    assert "&lt;script&gt;x" in body


@pytest.mark.parametrize("template", sorted(TEMPLATES.rglob("*.html")), ids=lambda p: p.name)
def test_templates_have_no_inline_script_style_or_safe(template):
    # Jinja comments never reach the browser, so they may mention <style>.
    src = re.sub(r"\{#.*?#\}", "", template.read_text(encoding="utf-8"), flags=re.S)
    # External scripts only: every <script> has a src and an empty body.
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script\s*>", src, re.I | re.S)
    assert len(scripts) == len(re.findall(r"<script\b", src, re.I))
    for attrs, body in scripts:
        assert re.search(r"\ssrc\s*=", attrs) and body.strip() == ""
    assert not re.search(r"<style\b", src, re.I)
    assert not re.search(r"\sstyle\s*=", src, re.I)
    assert not re.search(r"\son[a-z]+\s*=", src, re.I)
    assert "|safe" not in src.replace(" ", "")
    assert "autoescape false" not in src


# ---------------------------------------------------------------- read-write connection

@pytest.mark.parametrize("sql", [
    "INSERT INTO batting_stats (player_id, season_year, is_multi_team) VALUES (900003, 2017, 1)",
    "UPDATE players SET full_name = 'Hacked' WHERE player_id = 900001",
    "DELETE FROM teams",
    "CREATE TABLE sneaky (x)",
    "DROP TABLE player_notes",
    "ATTACH DATABASE ':memory:' AS other",
    "PRAGMA foreign_keys = OFF",
    "CREATE TEMP TABLE sneaky (x)",
    "ALTER TABLE player_notes ADD COLUMN x",
    "DELETE FROM seasons WHERE season_year = 2015",
])
def test_rw_authorizer_denies_everything_but_note_writes(app, test_db_path, caplog, sql):
    with app.app_context():
        from app.db import get_rw_db
        with pytest.raises(sqlite3.DatabaseError):
            get_rw_db().execute(sql)
    assert "authorizer denied" in caplog.text
    # nothing changed underneath
    conn = sqlite3.connect(test_db_path)
    try:
        assert conn.execute("SELECT full_name FROM players WHERE player_id = 900001").fetchone()[0] \
            == "Testy McFakerson"
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'player_notes'").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'sneaky'").fetchone()[0] == 0
    finally:
        conn.close()


def test_rw_connection_can_write_notes(app, test_db_path):
    with app.app_context():
        from app.db import get_rw_db
        db = get_rw_db()
        with db:
            db.execute("INSERT INTO player_notes (player_id, body) VALUES (?, ?)", (900001, "ok"))
            db.execute("UPDATE player_notes SET body = ? WHERE player_id = ?", ("ok2", 900001))
        assert db.execute("SELECT body, category FROM player_notes").fetchall()[0][:] == ("ok2", "general")
        with db:
            db.execute("DELETE FROM player_notes")


def test_rw_connection_enforces_foreign_key(app):
    with app.app_context():
        from app.db import get_rw_db
        db = get_rw_db()
        with pytest.raises(sqlite3.IntegrityError):
            with db:
                db.execute("INSERT INTO player_notes (player_id, body) VALUES (?, ?)", (999999, "ghost"))


def test_rw_connection_never_creates_a_db(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "absent.db", "SECRET_KEY": "x"})
    with app.app_context():
        from app.db import DatabaseMissing, get_rw_db
        with pytest.raises(DatabaseMissing):
            get_rw_db()
    assert not (tmp_path / "absent.db").exists()


@pytest.mark.parametrize("category, body", [
    ("scouting", "x"),
    ("general", "   "),
    ("general", "\n\n"),            # plain trim() would let these three through
    ("general", "\t"),
    ("general", " \r\n "),
    ("general", "x" * 2001),
])
def test_note_check_constraints_are_the_backstop(test_db_path, category, body):
    conn = sqlite3.connect(test_db_path)   # plain connection: no app validation in the way
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO player_notes (player_id, category, body) VALUES (?, ?, ?)",
                         (900001, category, body))
    finally:
        conn.close()


def test_note_check_allows_text_surrounded_by_whitespace(test_db_path):
    conn = sqlite3.connect(test_db_path)
    try:
        conn.execute("INSERT INTO player_notes (player_id, body) VALUES (?, ?)", (900001, "\t ok \r\n"))
        # 2000 characters after trimming, plus surrounding whitespace, is still valid
        conn.execute("INSERT INTO player_notes (player_id, body) VALUES (?, ?)",
                     (900001, "\n" + "x" * 2000 + "\n"))
    finally:
        conn.close()


def test_restrict_blocks_deleting_a_player_with_notes(test_db_path):
    conn = sqlite3.connect(test_db_path)   # plain connection, no authorizer
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            conn.execute("INSERT INTO player_notes (player_id, body) VALUES (?, ?)", (900001, "keep"))
        with pytest.raises(sqlite3.IntegrityError):
            with conn:
                conn.execute("DELETE FROM players WHERE player_id = ?", (900001,))
        assert conn.execute("SELECT COUNT(*) FROM players WHERE player_id = 900001").fetchone()[0] == 1
    finally:
        conn.close()


def test_session_cookie_flags(client):
    client.get("/player/900001/notes")            # CSRF token puts something in the session
    cookie = client.get_cookie("session")
    assert cookie is not None
    assert cookie.http_only
    assert cookie.same_site == "Lax"
