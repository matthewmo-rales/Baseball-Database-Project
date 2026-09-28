"""Blueprint "queries": the saved-query index and one page per saved query.

The slug is only ever a dict key. SQL comes from app.extensions
["saved_queries"] (parsed from queries/analysis.sql at startup), and request
values are bound to its ? placeholders by queries.execute(). Read-only
connection only.
"""
from flask import Blueprint, abort, current_app, render_template, request

from . import queries, stats
from .db import get_ro_db
from .main import MAX_QUERY_LEN, RESULT_LIMIT, search_players

bp = Blueprint("queries", __name__)

# Output columns that hold a player's name, linked when player_id is present.
NAME_COLUMNS = ("name", "full_name", "player")


def _saved():
    return current_app.extensions["saved_queries"]


@bp.route("/query")
def index():
    return render_template("query/index.html", groups=queries.by_tier(_saved()))


def _int_arg(name):
    """(raw, value): value None when the argument is absent or blank; 400 if
    present but not a whole number."""
    raw = request.args.get(name, "").strip()
    if not raw:
        return raw, None
    try:
        return raw, int(raw)
    except ValueError:
        abort(400, f"{name} must be a whole number.")


def _resolve_params(db, query, ctx):
    """Fill ctx from the request. Returns the bound values in param order, or
    None when the page should show a picker or a message instead of results."""
    sources = {spec.source for spec in query.params}
    values = {}

    _, player_id = _int_arg("player_id")
    if player_id is None or player_id <= 0:
        ctx["picker"] = search_players(request.args.get("q", ""))
        return None
    player = stats.get_player(db, player_id)
    if player is None:
        abort(404, f"There is no player with ID {player_id}.")
    ctx["player"] = player
    values["player_id"] = player_id

    if "season" in sources:
        qualified = stats.qualified_hitter_seasons(db, player_id)
        _, season = _int_arg("season")
        if season is None:
            ctx["season_choices"] = qualified
            return None
        if stats.get_season(db, season) is None:
            abort(400, f"{season} is not a season in this database.")
        if season not in qualified:
            ctx["not_qualified"] = season
            ctx["season_choices"] = qualified
            return None
        values["season"] = season

    return [values[spec.source] for spec in query.params]


@bp.route("/query/<slug>")
def show(slug):
    query = _saved().get(slug)
    if query is None:
        abort(404)
    db = get_ro_db()
    ctx = {"query": query, "limit": RESULT_LIMIT, "max_len": MAX_QUERY_LEN,
           "max_rows": queries.MAX_DISPLAY_ROWS}

    if query.requires_payroll:
        loaded, total = stats.payroll_coverage(db)
        ctx["payroll"] = {"loaded": loaded, "total": total}
        if loaded == 0:
            return render_template("query/show.html", **ctx)

    bound = []
    if query.params:
        bound = _resolve_params(db, query, ctx)
        if bound is None:
            return render_template("query/show.html", **ctx)
        ctx["bound"] = list(zip([spec.name for spec in query.params], bound))

    result = queries.execute(db, query.sql, tuple(bound))
    ctx["result"] = result
    ctx["links"] = _link_columns(result.columns)
    ctx["numeric"] = _numeric_columns(result)
    return render_template("query/show.html", **ctx)


def _link_columns(columns):
    """Which cells become links: {column index: ('player' | 'team', id column index)}."""
    links = {}
    if "player_id" in columns:
        pid = columns.index("player_id")
        name = next((columns.index(c) for c in NAME_COLUMNS if c in columns), pid)
        links[name] = ("player", pid)
    if "team_id" in columns:
        tid = columns.index("team_id")
        links[tid] = ("team", tid)
    return links


def _numeric_columns(result):
    """Indexes of columns whose non-NULL values are all numbers (right-aligned)."""
    numeric = set()
    for i in range(len(result.columns)):
        values = [row[i] for row in result.rows if row[i] is not None]
        if values and all(isinstance(v, (int, float)) for v in values):
            numeric.add(i)
    return numeric
