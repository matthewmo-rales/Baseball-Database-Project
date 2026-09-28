"""Blueprint "main": player search at /."""
from flask import Blueprint, render_template, request

from .db import get_ro_db, search_key

bp = Blueprint("main", __name__)

MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 50
RESULT_LIMIT = 25

# One round trip: match up to 25 players, then take first/last season across
# both stat tables for just those players. Two-way and pitcher-only players
# have rows in both tables (pitchers carry 0-PA batting rows).
SEARCH_SQL = """
WITH matched AS (
    SELECT player_id, full_name, birth_date, primary_position
    FROM players
    WHERE search_key(full_name) LIKE ? ESCAPE '\\'
    ORDER BY full_name, player_id
    LIMIT ?
),
appearances AS (
    SELECT player_id, season_year FROM batting_stats
    WHERE player_id IN (SELECT player_id FROM matched)
    UNION ALL
    SELECT player_id, season_year FROM pitching_stats
    WHERE player_id IN (SELECT player_id FROM matched)
)
SELECT m.player_id,
       m.full_name,
       CAST(strftime('%Y', m.birth_date) AS INTEGER) AS birth_year,
       m.primary_position,
       MIN(a.season_year) AS first_season,
       MAX(a.season_year) AS last_season
FROM matched m
LEFT JOIN appearances a ON a.player_id = m.player_id
GROUP BY m.player_id, m.full_name, m.birth_date, m.primary_position
ORDER BY m.full_name, m.player_id
"""


def like_pattern(raw):
    """Substring LIKE pattern with \\, % and _ escaped.

    Normalize first, then escape: NFKD maps fullwidth '％' and '＿' to '%' and
    '_', so escaping before normalizing would let those through as wildcards.
    """
    key = search_key(raw)
    escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    results = None
    message = None

    if q:
        if len(q) < MIN_QUERY_LEN:
            message = f"Enter at least {MIN_QUERY_LEN} characters."
        elif len(q) > MAX_QUERY_LEN:
            message = f"Search is limited to {MAX_QUERY_LEN} characters."
        else:
            results = get_ro_db().execute(
                SEARCH_SQL, (like_pattern(q), RESULT_LIMIT)
            ).fetchall()

    return render_template(
        "index.html",
        q=q,
        results=results,
        message=message,
        limit=RESULT_LIMIT,
        max_len=MAX_QUERY_LEN,
    )
