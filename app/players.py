"""Blueprint "players": player page, player-season page, player WAR chart JSON.

All reads use get_ro_db(). Nothing here writes; notes are managed on
/player/<id>/notes (blueprint "notes").
"""
from flask import Blueprint, abort, current_app, g, render_template

from . import charts, queries, stats
from .db import get_ro_db

bp = Blueprint("players", __name__)

BASELINE_NAMES = {
    "hitter": "Other qualified {pos} (mean)",
    "pitcher": "Other qualified P (mean)",
}


def player_or_404(db, player_id):
    player = stats.get_player(db, player_id)
    if player is None:
        abort(404, f"There is no player with ID {player_id}.")
    return player


@bp.route("/player/<int:player_id>")
def player(player_id):
    db = get_ro_db()
    p = player_or_404(db, player_id)
    batting = stats.batting_seasons(db, player_id)
    pitching = stats.pitching_seasons(db, player_id)
    note_count, notes = stats.recent_notes(db, player_id)
    has_war = bool(stats.war_series(db, player_id))
    g.renders_chart = has_war
    return render_template(
        "players/player.html",
        player=p,
        batting=batting,
        pitching=pitching,
        batting_totals=stats.batting_totals(db, player_id) if batting else None,
        pitching_totals=stats.pitching_totals(db, player_id) if pitching else None,
        note_count=note_count,
        notes=notes,
        has_war=has_war,
        baseline_kind=stats.baseline_kind(p["primary_position"]),
        qualified_seasons=stats.qualified_hitter_seasons(db, player_id),
        trajectory_slug=queries.slug_for(current_app.extensions["saved_queries"], "Q05"),
        comps_slug=queries.slug_for(current_app.extensions["saved_queries"], "Q18"),
    )


@bp.route("/player/<int:player_id>/season/<int:year>")
def season(player_id, year):
    db = get_ro_db()
    season_row = stats.get_season(db, year)
    if season_row is None:
        abort(404, f"{year} is not a season in this database.")
    p = player_or_404(db, player_id)
    batting = stats.batting_row(db, player_id, year)
    pitching = stats.pitching_row(db, player_id, year)
    if batting is None and pitching is None:
        abort(404, f"{p['full_name']} (ID {player_id}) has no batting or pitching record in {year}.")
    return render_template(
        "players/season.html",
        player=p,
        season=season_row,
        batting=batting,
        pitching=pitching,
        hitter_ranks=stats.hitter_ranks(db, player_id, year) if batting else None,
        pitcher_ranks=stats.pitcher_ranks(db, player_id, year) if pitching else None,
        min_pa=stats.min_pa(season_row["scheduled_games"]),
        min_outs=stats.min_outs(season_row["scheduled_games"]),
    )


@bp.route("/player/<int:player_id>/war-chart.json")
def war_chart(player_id):
    db = get_ro_db()
    p = player_or_404(db, player_id)
    series = stats.war_series(db, player_id)
    baseline = None
    baseline_name = None
    kind = stats.baseline_kind(p["primary_position"])
    if series and kind:
        first, last = series[0]["season_year"], series[-1]["season_year"]
        baseline = stats.baseline_series(db, player_id, p["primary_position"], first, last)
        baseline_name = BASELINE_NAMES[kind].format(pos=p["primary_position"])
    return charts.figure_response(charts.player_war_figure(p, series, baseline, baseline_name))
