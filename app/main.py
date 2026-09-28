"""Blueprint "main": player search at /."""
from collections import namedtuple

from flask import Blueprint, render_template, request

from .db import get_ro_db, search_key

bp = Blueprint("main", __name__)

MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 50
RESULT_LIMIT = 25

# One round trip: match up to RESULT_LIMIT + 1 players (the extra row only
# says "there are more"), then take first/last season across both stat tables
# for just those players. Two-way and pitcher-only players have rows in both
# tables (pitchers carry 0-PA batting rows). `player_id IS NOT ?` with NULL
# excludes nobody; the compare picker binds p1 there.
SEARCH_SQL = """
WITH matched AS (
    SELECT player_id, full_name, birth_date, primary_position
    FROM players
    WHERE search_key(full_name) LIKE ? ESCAPE '\\'
      AND player_id IS NOT ?
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

# results is None when no search ran (empty or invalid q); more is True when
# matches beyond the first RESULT_LIMIT exist.
Search = namedtuple("Search", "q results message more")


def like_pattern(raw):
    """Substring LIKE pattern with \\, % and _ escaped.

    Normalize first, then escape: NFKD maps fullwidth '％' and '＿' to '%' and
    '_', so escaping before normalizing would let those through as wildcards.
    """
    key = search_key(raw)
    escaped = key.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


def search_players(raw_q, exclude_id=None):
    """Validate and run a name search. Shared by / and the compare picker."""
    q = (raw_q or "").strip()
    if not q:
        return Search(q, None, None, False)
    if len(q) < MIN_QUERY_LEN:
        return Search(q, None, f"Enter at least {MIN_QUERY_LEN} characters.", False)
    if len(q) > MAX_QUERY_LEN:
        return Search(q, None, f"Search is limited to {MAX_QUERY_LEN} characters.", False)
    rows = get_ro_db().execute(
        SEARCH_SQL, (like_pattern(q), exclude_id, RESULT_LIMIT + 1)
    ).fetchall()
    return Search(q, rows[:RESULT_LIMIT], None, len(rows) > RESULT_LIMIT)


@bp.route("/")
def index():
    search = search_players(request.args.get("q", ""))
    return render_template(
        "index.html",
        q=search.q,
        results=search.results,
        message=search.message,
        more=search.more,
        limit=RESULT_LIMIT,
        max_len=MAX_QUERY_LEN,
    )
