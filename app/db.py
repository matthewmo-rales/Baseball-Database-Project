"""Read-only SQLite connection helpers.

Every request-path query goes through get_ro_db(): the file is opened with
mode=ro, so writes fail at the SQLite layer regardless of the SQL issued.
"""
import sqlite3
import unicodedata

from flask import current_app, g


class DatabaseMissing(Exception):
    """database/baseball.db has not been built yet."""


def search_key(text):
    """Accent- and case-insensitive key: NFKD, drop combining marks, casefold.

    SQLite's LIKE only folds ASCII case, so 'jose ramirez' would never match
    'José Ramírez' without this. Registered as a deterministic SQL function.
    """
    if text is None:
        return None
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def get_ro_db():
    if "ro_db" not in g:
        path = current_app.config["DATABASE"]
        if not path.is_file():
            raise DatabaseMissing(str(path))
        conn = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.create_function("search_key", 1, search_key, deterministic=True)
        g.ro_db = conn
    return g.ro_db


def close_db(exc=None):
    conn = g.pop("ro_db", None)
    if conn is not None:
        conn.close()


def init_app(app):
    app.teardown_appcontext(close_db)
