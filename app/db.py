"""SQLite connection helpers.

Every read goes through get_ro_db(): the file is opened with mode=ro, so
writes fail at the SQLite layer regardless of the SQL issued.

get_rw_db() is for the notes blueprint's POST handlers only. Its authorizer
denies everything except reads, functions, transactions and row writes to
player_notes, so even a bug in a handler cannot touch the loaded data.
"""
import logging
import sqlite3
import unicodedata

from flask import current_app, g

log = logging.getLogger(__name__)

WRITABLE_TABLE = "player_notes"
_ALWAYS_ALLOWED = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    sqlite3.SQLITE_TRANSACTION,
}
_ROW_WRITES = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE}

# action code -> name, for readable denial logs. Listed explicitly: the module
# also exports result codes whose numbers collide with these (18 = INSERT/TOOBIG).
_ACTION_NAMES = {
    getattr(sqlite3, "SQLITE_" + name): name
    for name in (
        "CREATE_INDEX", "CREATE_TABLE", "CREATE_TEMP_INDEX", "CREATE_TEMP_TABLE",
        "CREATE_TEMP_TRIGGER", "CREATE_TEMP_VIEW", "CREATE_TRIGGER", "CREATE_VIEW",
        "DELETE", "DROP_INDEX", "DROP_TABLE", "DROP_TEMP_INDEX", "DROP_TEMP_TABLE",
        "DROP_TEMP_TRIGGER", "DROP_TEMP_VIEW", "DROP_TRIGGER", "DROP_VIEW", "INSERT",
        "PRAGMA", "READ", "SELECT", "TRANSACTION", "UPDATE", "ATTACH", "DETACH",
        "ALTER_TABLE", "REINDEX", "ANALYZE", "CREATE_VTABLE", "DROP_VTABLE",
        "FUNCTION", "SAVEPOINT", "RECURSIVE",
    )
    if hasattr(sqlite3, "SQLITE_" + name)
}


# SQLite INTEGER is 64-bit signed. sqlite3 raises OverflowError when a larger
# Python int is bound, so request integers are capped at this before any query.
SQLITE_INT_MAX = 2**63 - 1


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


def _connect(mode):
    path = current_app.config["DATABASE"]
    if not path.is_file():
        raise DatabaseMissing(str(path))
    # mode=ro / mode=rw never create the file (plain connect() would).
    conn = sqlite3.connect(path.as_uri() + "?mode=" + mode, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_ro_db():
    if "ro_db" not in g:
        conn = _connect("ro")
        conn.create_function("search_key", 1, search_key, deterministic=True)
        g.ro_db = conn
    return g.ro_db


def notes_authorizer(action, arg1, arg2, db_name, source):
    """Default deny. For INSERT/UPDATE/DELETE, arg1 is the table name."""
    if action in _ALWAYS_ALLOWED:
        return sqlite3.SQLITE_OK
    if action in _ROW_WRITES and arg1 == WRITABLE_TABLE and db_name == "main":
        return sqlite3.SQLITE_OK
    log.warning(
        "sqlite authorizer denied %s (%r, %r) on db %r",
        _ACTION_NAMES.get(action, action), arg1, arg2, db_name,
    )
    return sqlite3.SQLITE_DENY


def get_rw_db():
    """Read-write connection that can only write player_notes."""
    if "rw_db" not in g:
        conn = _connect("rw")   # PRAGMA foreign_keys runs before the authorizer
        conn.set_authorizer(notes_authorizer)
        g.rw_db = conn
    return g.rw_db


def close_db(exc=None):
    for key in ("ro_db", "rw_db"):
        conn = g.pop(key, None)
        if conn is not None:
            conn.close()


# Endpoints that work without the database: CSS/JS and the plotly bundle,
# so the setup page itself renders styled.
_NO_DB_ENDPOINTS = {"static", "charts.plotly_js", "charts.plotly_css", "charts.maplibre_css"}


def require_database():
    """Show the setup page on every page (including / with no search) until
    database/baseball.db is built, not only on pages that happen to query."""
    from flask import request
    if request.endpoint in _NO_DB_ENDPOINTS or request.endpoint is None:
        return
    if not current_app.config["DATABASE"].is_file():
        raise DatabaseMissing(str(current_app.config["DATABASE"]))


def init_app(app):
    app.before_request(require_database)
    app.teardown_appcontext(close_db)
