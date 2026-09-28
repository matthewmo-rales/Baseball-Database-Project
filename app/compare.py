"""Blueprint "compare": two players side by side, pickers, and the compare chart JSON.

Id validation matches the saved queries: a missing id shows a picker; an id
that is present but not a positive whole number is a 400.
"""
from flask import Blueprint, abort, g, render_template, request

from . import charts, stats
from .db import get_ro_db
from .main import MAX_QUERY_LEN, RESULT_LIMIT, search_players
from .players import player_or_404
from .query_views import positive_int_arg

bp = Blueprint("compare", __name__)


def _side(db, player_id):
    return {
        "player": player_or_404(db, player_id),
        "batting": stats.batting_totals(db, player_id),
        "pitching": stats.pitching_totals(db, player_id),
        **stats.summary(db, player_id),
    }


def _picker(player, other_id):
    """player None: choose the first player (keeping p2 if given);
    otherwise choose a second player for `player`."""
    exclude = player["player_id"] if player else other_id
    return render_template(
        "compare/picker.html",
        player=player,
        other_id=other_id,
        search=search_players(request.args.get("q", ""), exclude_id=exclude),
        limit=RESULT_LIMIT,
        max_len=MAX_QUERY_LEN,
    )


@bp.route("/compare")
def compare():
    p1 = positive_int_arg("p1")
    p2 = positive_int_arg("p2")
    if p1 is not None and p1 == p2:
        abort(400, "Choose two different players.")
    db = get_ro_db()
    if p1 is None:
        if p2 is not None:
            player_or_404(db, p2)
        return _picker(None, p2)
    if p2 is None:
        return _picker(player_or_404(db, p1), None)
    sides = [_side(db, p1), _side(db, p2)]
    g.renders_chart = True
    return render_template("compare/compare.html", sides=sides, p1=p1, p2=p2)


@bp.route("/compare/war-chart.json")
def war_chart():
    # JSON has no picker: both ids are required here.
    p1 = positive_int_arg("p1")
    p2 = positive_int_arg("p2")
    if p1 is None or p2 is None:
        abort(400, "p1 and p2 are both required.")
    if p1 == p2:
        abort(400, "Choose two different players.")
    db = get_ro_db()
    player1 = player_or_404(db, p1)
    player2 = player_or_404(db, p2)
    fig = charts.compare_war_figure(
        player1, stats.war_series(db, p1), player2, stats.war_series(db, p2)
    )
    return charts.figure_response(fig)
