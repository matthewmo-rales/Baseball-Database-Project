"""Blueprint "teams": /team/<team_id> with season history and a roster.

team_id is checked against ^[A-Z]{2,4}$ before any query runs, then looked
up with a bound parameter. Read-only connection only.
"""
import re

from flask import Blueprint, abort, render_template

from . import stats
from .db import get_ro_db
from .query_views import season_arg

bp = Blueprint("teams", __name__)

TEAM_ID_RE = re.compile(r"[A-Z]{2,4}")


@bp.route("/team/<team_id>")
def team(team_id):
    if not TEAM_ID_RE.fullmatch(team_id):
        abort(404)
    db = get_ro_db()
    t = stats.get_team(db, team_id)
    if t is None:
        abort(404, f"There is no team with ID {team_id}.")
    history = stats.team_seasons(db, team_id)
    season = season_arg(db)
    if season is None and history:
        season = history[-1]["season_year"]        # latest season with a team_stats row
    loaded, _total = stats.payroll_coverage(db)
    return render_template(
        "teams/team.html",
        team=t,
        history=history,
        season=season,
        roster_seasons=[r["season_year"] for r in history],
        hitters=stats.roster_hitters(db, team_id, season) if season else [],
        pitchers=stats.roster_pitchers(db, team_id, season) if season else [],
        payroll_loaded=loaded,
    )
