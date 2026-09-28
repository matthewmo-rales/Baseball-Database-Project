"""Blueprint "queries": the saved-query index, one page per saved query, the
saved-query charts (JSON + the /charts gallery).

The slug is only ever a dict key. SQL comes from app.extensions
["saved_queries"] (parsed from queries/analysis.sql at startup), and request
values are bound to its ? placeholders by queries.execute(). Charts are built
from that same Result; there is no chart SQL. Read-only connection only.
"""
from flask import Blueprint, abort, current_app, render_template, request

from . import charts, queries, stats
from .db import get_ro_db
from .main import MAX_QUERY_LEN, RESULT_LIMIT, search_players

bp = Blueprint("queries", __name__)

# Output columns that hold a player's name, linked when player_id is present.
NAME_COLUMNS = ("name", "full_name", "player")
# Output column holding a team's FanGraphs abbreviation (Q01, Q03, Q11, ...).
TEAM_ABBREV_COLUMN = "team"


def _saved():
    return current_app.extensions["saved_queries"]


def _query_or_404(slug):
    query = _saved().get(slug)
    if query is None:
        abort(404)
    return query


def positive_int_arg(name):
    """None when the argument is absent or blank (the caller shows a picker);
    400 when present but not a positive whole number."""
    raw = request.args.get(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        abort(400, f"{name} must be a positive whole number.")
    if value <= 0:
        abort(400, f"{name} must be a positive whole number.")
    return value


def season_arg(db, name="season"):
    """A season in the seasons table, None if absent; 400 otherwise."""
    raw = request.args.get(name, "").strip()
    if not raw:
        return None
    try:
        season = int(raw)
    except ValueError:
        abort(400, f"{name} must be a season year.")
    if stats.get_season(db, season) is None:
        abort(400, f"{season} is not a season in this database.")
    return season


def _all_seasons(db):
    return [r[0] for r in db.execute("SELECT season_year FROM seasons ORDER BY season_year")]


def _takes_season_param(query):
    return any(spec.source == "season" for spec in query.params)


@bp.route("/query")
def index():
    return render_template("query/index.html", groups=queries.by_tier(_saved()))


def _resolve_params(db, query, ctx):
    """Fill ctx from the request. Returns the bound values in param order, or
    None when the page should show a picker or a message instead of results."""
    values = {}

    player_id = positive_int_arg("player_id")
    if player_id is None:
        ctx["picker"] = search_players(request.args.get("q", ""))
        return None
    player = stats.get_player(db, player_id)
    if player is None:
        abort(404, f"There is no player with ID {player_id}.")
    ctx["player"] = player
    values["player_id"] = player_id

    if _takes_season_param(query):
        qualified = stats.qualified_hitter_seasons(db, player_id)
        season = season_arg(db)
        if season is None:
            ctx["season_choices"] = qualified
            return None
        if season not in qualified:
            ctx["not_qualified"] = season
            ctx["season_choices"] = qualified
            return None
        values["season"] = season

    return [values[spec.source] for spec in query.params]


def _payroll_missing(db, query, ctx):
    if not query.requires_payroll:
        return False
    loaded, total = stats.payroll_coverage(db)
    ctx["payroll"] = {"loaded": loaded, "total": total}
    return loaded == 0


@bp.route("/query/<slug>")
def show(slug):
    query = _query_or_404(slug)
    db = get_ro_db()
    ctx = {"query": query, "limit": RESULT_LIMIT, "max_len": MAX_QUERY_LEN,
           "max_rows": queries.MAX_DISPLAY_ROWS}

    # Validate the post-query filter before running anything. Q18's own
    # ?season= is its target season, not a filter.
    offers_filter = not _takes_season_param(query)
    season = season_arg(db) if offers_filter else None

    if _payroll_missing(db, query, ctx):
        return render_template("query/show.html", **ctx)

    bound = []
    if query.params:
        bound = _resolve_params(db, query, ctx)
        if bound is None:
            return render_template("query/show.html", **ctx)
        ctx["bound"] = list(zip([spec.name for spec in query.params], bound))

    result = queries.execute(db, query.sql, tuple(bound))
    has_season = queries.season_column(result.columns) is not None
    if season is not None and not has_season:
        abort(400, "This query has no season column to filter on.")
    shown = queries.filter_season(result, season)

    ctx.update(
        result=result,
        shown=shown,
        display_rows=shown.rows[:queries.MAX_DISPLAY_ROWS],
        season=season,
        season_filter=offers_filter and has_season,
        seasons=_all_seasons(db),
        links=_link_columns(result.columns),
        team_ids=_team_ids(db) if TEAM_ABBREV_COLUMN in result.columns else {},
        numeric=_numeric_columns(result),
        season_idx=queries.season_column(result.columns),
    )
    if query.chart:
        ctx["chart_src_args"] = {"slug": slug, **({"season": season} if season else {})}
        if query.chart == "woba_leaderboard" and season is None and result.rows:
            ctx["chart_default_season"] = max(r[queries.season_column(result.columns)]
                                              for r in result.rows)
    return render_template("query/show.html", **ctx)


@bp.route("/query/<slug>/chart.json")
def chart(slug):
    query = _query_or_404(slug)
    if not query.chart or query.params:
        abort(404)
    db = get_ro_db()
    season = season_arg(db)
    if _payroll_missing(db, query, {}):
        abort(404)
    result = queries.execute(db, query.sql, ())
    if season is not None and queries.season_column(result.columns) is None:
        abort(400, "This chart has no season to filter on.")
    fig = charts.QUERY_CHARTS[query.chart](queries.filter_season(result, season), season)
    return charts.figure_response(fig)


@bp.route("/charts")
def gallery():
    db = get_ro_db()
    loaded, _total = stats.payroll_coverage(db)
    items = [q for q in sorted(_saved().values(), key=queries._file_order) if q.chart]
    return render_template("query/charts.html", items=items, payroll_loaded=loaded)


def _link_columns(columns):
    """Which cells become links: {column index: (kind, id column index)}."""
    links = {}
    if "player_id" in columns:
        pid = columns.index("player_id")
        name = next((columns.index(c) for c in NAME_COLUMNS if c in columns), pid)
        links[name] = ("player", pid)
    if "team_id" in columns:
        tid = columns.index("team_id")
        links[tid] = ("team", tid)
    elif TEAM_ABBREV_COLUMN in columns:
        tid = columns.index(TEAM_ABBREV_COLUMN)
        links[tid] = ("team_abbrev", tid)
    return links


def _team_ids(db):
    """fangraphs_abbrev -> team_id, for linking a query's 'team' column."""
    return {r[0]: r[1] for r in db.execute(
        "SELECT fangraphs_abbrev, team_id FROM teams WHERE fangraphs_abbrev IS NOT NULL")}


def _numeric_columns(result):
    """Indexes of columns whose non-NULL values are all numbers (right-aligned)."""
    numeric = set()
    for i in range(len(result.columns)):
        values = [row[i] for row in result.rows if row[i] is not None]
        if values and all(isinstance(v, (int, float)) for v in values):
            numeric.add(i)
    return numeric
