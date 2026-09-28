"""Flask application factory for the baseball analytics app.

Run locally with:  flask --app app run --debug
Debug mode is never set in code.
"""
import os
import secrets
from pathlib import Path

from flask import Flask, render_template
from werkzeug.routing import IntegerConverter
from flask_wtf import CSRFProtect
from flask_wtf.csrf import CSRFError

from . import charts, db, formatting, queries

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "form-action 'self'"
)

csrf = CSRFProtect()


class SqliteIntConverter(IntegerConverter):
    """<int:...> capped at SQLite's INTEGER max: a larger path id doesn't
    match the route (404) instead of raising OverflowError when bound.
    The digit limit also keeps int() from raising ValueError on very long
    strings (Python's 4,300-digit cap), which Werkzeug doesn't catch."""

    regex = r"\d{1,19}"

    def __init__(self, url_map, *args, **kwargs):
        kwargs.setdefault("max", db.SQLITE_INT_MAX)
        super().__init__(url_map, *args, **kwargs)


def create_app(test_config=None):
    app = Flask(__name__, instance_path=str(PROJECT_ROOT / "instance"))
    # Before any blueprint registers its rules, so every <int:...> uses it.
    app.url_map.converters["int"] = SqliteIntConverter
    app.config.from_mapping(
        DATABASE=PROJECT_ROOT / "database" / "baseball.db",
        SESSION_COOKIE_SAMESITE="Lax",
        # The largest legitimate request is a note: 2,000 characters plus a
        # CSRF token and a category. 16 KB leaves room for multi-byte text.
        MAX_CONTENT_LENGTH=16 * 1024,
        # SESSION_COOKIE_SECURE stays False: local dev is plain http, and a
        # Secure cookie would never be sent back, breaking CSRF and flashes.
        # Set it to True in any deployment behind HTTPS. HttpOnly is Flask's
        # default (on) and is left alone.
    )
    if test_config is not None:
        app.config.update(test_config)
    app.config["DATABASE"] = Path(app.config["DATABASE"]).resolve()

    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_secret_key(Path(app.instance_path))

    csrf.init_app(app)
    db.init_app(app)
    formatting.init_app(app)
    charts.init_app(app)
    queries.init_app(app)     # parses queries/analysis.sql; raises on any mismatch

    from . import compare, main, notes, players, query_views, teams
    app.register_blueprint(main.bp)
    app.register_blueprint(notes.bp)
    app.register_blueprint(players.bp)
    app.register_blueprint(compare.bp)
    app.register_blueprint(charts.bp)
    app.register_blueprint(query_views.bp)
    app.register_blueprint(teams.bp)

    _register_security_headers(app)
    _register_error_handlers(app)
    return app


def _load_secret_key(instance_dir):
    """FLASK_SECRET_KEY from the environment, else a key persisted in instance/."""
    env_key = os.environ.get("FLASK_SECRET_KEY")
    if env_key:
        return env_key
    key_file = instance_dir / "secret_key"
    if key_file.exists():
        return key_file.read_text(encoding="ascii").strip()
    instance_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="ascii")
    return key


def _register_security_headers(app):
    @app.after_request
    def set_headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response


def _custom_message(e):
    """The text passed to abort(code, "..."), or None for Werkzeug's default."""
    if e.description and e.description != type(e).description:
        return e.description
    return None


def _register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(e):
        return render_template("errors/400.html", message=_custom_message(e)), 400

    @app.errorhandler(CSRFError)
    def csrf_failed(e):
        return render_template("errors/400.html", csrf_failed=True), 400

    @app.errorhandler(404)
    def not_found(e):
        return render_template("errors/404.html", message=_custom_message(e)), 404

    @app.errorhandler(405)
    def method_not_allowed(e):
        # keep Werkzeug's Allow header, swap in the friendly body
        return render_template("errors/405.html"), 405, {"Allow": ", ".join(e.valid_methods or [])}

    @app.errorhandler(413)
    def too_large(e):
        return render_template("errors/413.html"), 413

    @app.errorhandler(500)
    def server_error(e):
        # Flask has already logged the traceback via app.log_exception before
        # this handler runs; the page itself never shows exception details.
        return render_template("errors/500.html"), 500

    @app.errorhandler(OverflowError)
    def integer_overflow(e):
        # Backstop only: request integers are range-checked before binding
        # (SqliteIntConverter, query_views._int_or_none). Logged so a gap shows up.
        app.logger.warning("OverflowError reached the error handler: %s", e)
        return render_template("errors/400.html"), 400

    @app.errorhandler(db.DatabaseMissing)
    def database_missing(e):
        return render_template("errors/db_missing.html"), 503
