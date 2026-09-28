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
    src = template.read_text(encoding="utf-8")
    assert not re.search(r"<script\b", src, re.I)
    assert not re.search(r"<style\b", src, re.I)
    assert not re.search(r"\sstyle\s*=", src, re.I)
    assert not re.search(r"\son[a-z]+\s*=", src, re.I)
    assert "|safe" not in src.replace(" ", "")
    assert "autoescape false" not in src
