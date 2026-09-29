"""Blueprint "teams": /teams (list and search) and /team/<team_id> with
season history and a roster.

team_id is checked against ^[A-Z]{2,4}$ before any query runs, then looked
up with a bound parameter. Read-only connection only.
"""
import re
from itertools import groupby

from flask import Blueprint, abort, redirect, render_template, request, url_for

from . import stats
from .db import get_ro_db
from .main import MAX_QUERY_LEN, length_problem, like_pattern
from .query_views import season_arg

bp = Blueprint("teams", __name__)

TEAM_ID_RE = re.compile(r"[A-Z]{2,4}")

# League and division come through divisions; East/Central/West order is
# derived from division_name, never from division ids.
TEAM_LIST_SELECT = """
SELECT t.team_id, t.team_name, t.city, d.league, d.division_name
  FROM teams     AS t
  JOIN divisions AS d ON d.division_id = t.division_id
"""
TEAM_LIST_ORDER = """
 ORDER BY d.league,
          CASE d.division_name WHEN 'East' THEN 1 WHEN 'Central' THEN 2 WHEN 'West' THEN 3 ELSE 4 END,
          d.division_name, t.team_name, t.team_id
"""
ALL_TEAMS_SQL = TEAM_LIST_SELECT + TEAM_LIST_ORDER
# Checked first: an exact abbreviation wins over name and city substrings
# ('lad' is inside 'Philadelphia').
TEAM_BY_ID_SQL = "SELECT team_id FROM teams WHERE team_id = ?"
# Name and city by substring (accent- and case-insensitive, pattern escaped in
# Python).
SEARCH_TEAMS_SQL = TEAM_LIST_SELECT + """
 WHERE search_key(t.team_name) LIKE ? ESCAPE '\\'
    OR search_key(t.city)      LIKE ? ESCAPE '\\'
""" + TEAM_LIST_ORDER


def group_teams(rows):
    """[(league, [(division_name, [team rows])])], keeping the SQL order."""
    return [
        (league, [(division, list(teams)) for division, teams in groupby(rows, key=lambda r: r["division_name"])])
        for league, rows in groupby(rows, key=lambda r: r["league"])
    ]


@bp.route("/teams")
def index():
    db = get_ro_db()
    q = request.args.get("q", "").strip()
    message = length_problem(q) if q else None
    if not q or message:
        rows, searched = db.execute(ALL_TEAMS_SQL).fetchall(), False
    else:
        # Redirects are built from the id read from the DB, never from the request.
        exact = db.execute(TEAM_BY_ID_SQL, (q.upper(),)).fetchone()
        if exact is not None:
            return redirect(url_for("teams.team", team_id=exact["team_id"]))
        pattern = like_pattern(q)
        rows, searched = db.execute(SEARCH_TEAMS_SQL, (pattern, pattern)).fetchall(), True
        if len(rows) == 1:
            return redirect(url_for("teams.team", team_id=rows[0]["team_id"]))
    return render_template(
        "teams/index.html",
        q=q,
        message=message,
        searched=searched,
        count=len(rows),
        leagues=group_teams(rows),
        max_len=MAX_QUERY_LEN,
    )


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
