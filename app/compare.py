"""Blueprint "compare": two players side by side, a picker, and the compare chart JSON."""
from flask import Blueprint, abort, g, render_template, request

from . import charts, stats
from .db import get_ro_db
from .main import MAX_QUERY_LEN, RESULT_LIMIT, search_players
from .players import player_or_404

bp = Blueprint("compare", __name__)


def _positive_id(name):
    """The id in request.args[name]; None if absent; 400 if not a positive integer."""
    if name not in request.args:
        return None
    value = request.args.get(name, type=int)
    if value is None or value <= 0:
        abort(400, f"{name} must be a positive player ID.")
    return value


def _validated_ids(require_p2):
    p1 = _positive_id("p1")
    if p1 is None:
        abort(400, "Choose a first player: p1 must be a positive player ID.")
    p2 = _positive_id("p2")
    if p2 is None and require_p2:
        abort(400, "Choose a second player: p2 must be a positive player ID.")
    if p1 == p2:
        abort(400, "Choose two different players.")
    return p1, p2


def _side(db, player_id):
    return {
        "player": player_or_404(db, player_id),
        "batting": stats.batting_totals(db, player_id),
        "pitching": stats.pitching_totals(db, player_id),
        **stats.summary(db, player_id),
    }


@bp.route("/compare")
def compare():
    p1, p2 = _validated_ids(require_p2=False)
    db = get_ro_db()
    if p2 is None:
        player1 = player_or_404(db, p1)
        search = search_players(request.args.get("q", ""), exclude_id=p1)
        return render_template(
            "compare/picker.html",
            player=player1,
            search=search,
            limit=RESULT_LIMIT,
            max_len=MAX_QUERY_LEN,
        )
    sides = [_side(db, p1), _side(db, p2)]
    g.renders_chart = True
    return render_template("compare/compare.html", sides=sides, p1=p1, p2=p2)


@bp.route("/compare/war-chart.json")
def war_chart():
    p1, p2 = _validated_ids(require_p2=True)
    db = get_ro_db()
    player1 = player_or_404(db, p1)
    player2 = player_or_404(db, p2)
    fig = charts.compare_war_figure(
        player1, stats.war_series(db, p1), player2, stats.war_series(db, p2)
    )
    return charts.figure_response(fig)
