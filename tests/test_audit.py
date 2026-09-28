"""Security sweeps: CSRF on every POST route, headers on every response type,
request size, and the cheap grep checks (JS sinks, template escapes, debug
settings, tracked files)."""
import re
import subprocess
from pathlib import Path

import pytest

from app import CSP, create_app
from tests.conftest import ROOT, query_db

HANK = 900010
NOTE_BODY = "Existing note."


def seed_note(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    with conn:
        conn.execute("INSERT INTO player_notes (note_id, player_id, body) VALUES (1, ?, ?)", (HANK, NOTE_BODY))
    conn.close()


def fill(rule):
    path = rule.rule
    for name in rule.arguments:
        value = {"player_id": str(HANK), "note_id": "1"}[name]
        path = re.sub(r"<(?:[^:<>]+:)?" + name + ">", value, path)
    return path


# ---------------------------------------------------------------- CSRF sweep

def post_rules(app):
    return [r for r in app.url_map.iter_rules() if "POST" in r.methods]


def test_there_are_post_routes_to_check(app):
    endpoints = {r.endpoint for r in post_rules(app)}
    assert endpoints == {"notes.list_notes", "notes.edit_note", "notes.delete_note"}, (
        "POST routes changed: every one must be covered by the CSRF sweep below")


def test_every_post_route_requires_csrf(app, client, test_db_path):
    """Found through url_map, so a new POST route is swept automatically."""
    seed_note(test_db_path)
    before = query_db(test_db_path, "SELECT * FROM player_notes ORDER BY note_id")
    for rule in post_rules(app):
        url = fill(rule)
        for data in ({"category": "general", "body": "sneaky"},
                     {"category": "general", "body": "sneaky", "csrf_token": "forged"}):
            resp = client.post(url, data=data)
            assert resp.status_code == 400, url
            assert "nothing was saved" in resp.get_data(as_text=True)
    assert query_db(test_db_path, "SELECT * FROM player_notes ORDER BY note_id") == before


def test_csrf_is_not_disabled_or_exempted(app):
    from app import csrf
    assert app.config.get("WTF_CSRF_ENABLED", True) is True
    assert not csrf._exempt_views and not csrf._exempt_blueprints


# ---------------------------------------------------------------- headers sweep

def boom_app(test_db_path):
    app = create_app({"TESTING": True, "PROPAGATE_EXCEPTIONS": False,
                      "DATABASE": test_db_path, "SECRET_KEY": "test-only-not-secret"})

    @app.route("/boom")
    def boom():
        raise RuntimeError("forced")
    return app


@pytest.mark.parametrize("method, url, status, kind", [
    ("get", "/", 200, "text/html"),
    ("get", f"/player/{HANK}", 200, "text/html"),
    ("get", "/compare?p1=abc", 400, "text/html"),
    ("get", "/no/such/page", 404, "text/html"),
    ("get", "/notes/1/delete", 405, "text/html"),
    ("post", f"/player/{HANK}/notes", 413, "text/html"),
    ("get", "/boom", 500, "text/html"),
    ("get", f"/player/{HANK}/war-chart.json", 200, "application/json"),
    ("get", "/query/top-woba-by-season/chart.json", 200, "application/json"),
    ("get", "/vendor/plotly.min.js", 200, "application/javascript"),
    ("get", "/vendor/plotly.css", 200, "text/css"),
    ("get", "/static/css/style.css", 200, "text/css"),
    ("get", "/static/js/charts.js", 200, "text/javascript"),
])
def test_security_headers_on_every_response_type(test_db_path, method, url, status, kind):
    client = boom_app(test_db_path).test_client()
    kwargs = {"data": {"body": "x" * 20_000}} if status == 413 else {}
    resp = getattr(client, method)(url, **kwargs)
    assert resp.status_code == status
    assert resp.mimetype == kind
    assert resp.headers["Content-Security-Policy"] == CSP
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["Referrer-Policy"] == "same-origin"


def test_500_page_is_friendly(test_db_path):
    body = boom_app(test_db_path).test_client().get("/boom").get_data(as_text=True)
    assert "Something went wrong" in body and "forced" not in body and "Traceback" not in body


# ---------------------------------------------------------------- request size

def test_max_content_length_is_16kb(app):
    assert app.config["MAX_CONTENT_LENGTH"] == 16 * 1024


def test_oversized_post_is_413_and_saves_nothing(client, test_db_path):
    resp = client.post(f"/player/{HANK}/notes", data={"body": "x" * 20_000, "category": "general"})
    body = resp.get_data(as_text=True)
    assert resp.status_code == 413
    assert "too much to send" in body and "nothing was saved" in body
    assert "Traceback" not in body
    assert query_db(test_db_path, "SELECT COUNT(*) FROM player_notes") == [(0,)]


def test_a_max_length_note_still_fits(client):
    from tests.conftest import csrf_token
    token = csrf_token(client, f"/player/{HANK}/notes")
    resp = client.post(f"/player/{HANK}/notes",
                       data={"csrf_token": token, "category": "general", "body": "é" * 2000})
    assert resp.status_code == 302


# ---------------------------------------------------------------- grep checks

APP_DIR = ROOT / "app"


def sources(pattern):
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(APP_DIR.rglob(pattern))]


@pytest.mark.parametrize("sink", ["innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                                  "eval(", "new Function"])
def test_js_has_no_html_or_eval_sinks(sink):
    for path, text in sources("*.js"):
        assert sink not in text, f"{sink} in {path}"


@pytest.mark.parametrize("pattern", [r"\|\s*safe\b", r"Markup\(", r"autoescape\s+false"])
def test_templates_have_no_escape_bypasses(pattern):
    for path, text in sources("*.html"):
        assert not re.search(pattern, text), f"{pattern} in {path}"


@pytest.mark.parametrize("pattern", [r"render_template_string", r"debug\s*=\s*True", r"\.run\(",
                                     r"0\.0\.0\.0", r"SECRET_KEY\s*[=:]\s*['\"]", r"\bMarkup\b"])
def test_python_has_no_risky_settings(pattern):
    for path, text in sources("*.py"):
        assert not re.search(pattern, text), f"{pattern} in {path}"


def _git_ls_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    return out.stdout.splitlines()


def test_no_instance_or_database_data_is_tracked():
    tracked = _git_ls_files()
    assert not [f for f in tracked if f.startswith("instance/")]
    assert [f for f in tracked if f.startswith("database/")] == ["database/README.md",
                                                                 "database/seed_reference.sql"]
    assert not [f for f in tracked if f.endswith((".db", ".sqlite", ".env")) or "secret_key" in f]
