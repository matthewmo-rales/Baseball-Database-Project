"""Read-only queries behind the player, season and compare pages and the WAR charts.

Every function takes the connection from get_ro_db(). Rates in the totals are
recomputed from summed components (never averaged, never taken from the
rounded generated columns), and multiplied by 1.0 so integer division can't
truncate.
"""
import math

# MLB qualification rules. The SQL below spells the same
# constants inline; these are for the "needs N" text on the season page.
PA_PER_GAME = 3.1
OUTS_PER_GAME = 3

# Combined WAR per player-season, exactly as Q05: batting + pitching via
# UNION ALL (so two-way players are whole), NULL-only seasons dropped.
# Every row of both tables counts, including 0-PA batting rows.
COMBINED_WAR_CTE = """
war AS (
    SELECT player_id, season_year, SUM(war) AS war
    FROM (
        SELECT player_id, season_year, war FROM batting_stats
        UNION ALL
        SELECT player_id, season_year, war FROM pitching_stats
    )
    GROUP BY player_id, season_year
    HAVING SUM(war) IS NOT NULL
)"""


def get_player(db, player_id):
    return db.execute(
        """SELECT player_id, full_name, primary_position, bats, throws, birth_date,
                  CAST(strftime('%Y', birth_date) AS INTEGER) AS birth_year, debut_year
             FROM players
            WHERE player_id = ?""",
        (player_id,),
    ).fetchone()


def get_season(db, year):
    return db.execute(
        "SELECT season_year, scheduled_games, is_shortened FROM seasons WHERE season_year = ?",
        (year,),
    ).fetchone()


# ---------------------------------------------------------------- player page

# Which batting rows the pages show. A PA = 0 row is shown only when the
# player has no pitching row that season: that keeps defensive and pinch-
# running appearances (which can carry a little WAR) and hides the 0-PA
# placeholder rows pitchers carry. Used as-is on batting_stats aliased "b";
# a fixed string, never built from input.
SHOWN_BATTING_ROW = """(b.plate_appearances > 0 OR NOT EXISTS (
        SELECT 1 FROM pitching_stats AS ps
         WHERE ps.player_id = b.player_id AND ps.season_year = b.season_year))"""


def batting_seasons(db, player_id):
    # Base table, not v_batting_season: the view drops every PA = 0 row.
    # FanGraphs stores wOBA as 0 on PA = 0 rows; show it as missing.
    return db.execute(
        """SELECT b.season_year, b.team_id, t.fangraphs_abbrev, b.is_multi_team,
                  b.games, b.plate_appearances, b.home_runs, b.runs, b.rbi, b.stolen_bases,
                  b.batting_avg, b.obp, b.slg,
                  CASE WHEN b.plate_appearances > 0 THEN b.woba END AS woba,
                  b.wrc_plus, b.war,
                  s.is_shortened, s.scheduled_games
             FROM batting_stats AS b
             JOIN seasons    AS s ON s.season_year = b.season_year
             LEFT JOIN teams AS t ON t.team_id = b.team_id
            WHERE b.player_id = ? AND """ + SHOWN_BATTING_ROW + """
            ORDER BY b.season_year""",
        (player_id,),
    ).fetchall()


def pitching_seasons(db, player_id):
    # Base table, not v_pitching_season: the view has no ip_display.
    return db.execute(
        """SELECT p.season_year, p.team_id, t.fangraphs_abbrev, p.is_multi_team,
                  p.games, p.games_started, p.ip_display, p.strikeouts, p.walks,
                  p.era, p.whip, p.k_per_9, p.fip, p.xfip, p.era_minus, p.war,
                  s.is_shortened, s.scheduled_games
             FROM pitching_stats AS p
             JOIN seasons    AS s ON s.season_year = p.season_year
             LEFT JOIN teams AS t ON t.team_id = p.team_id
            WHERE p.player_id = ?
            ORDER BY p.season_year""",
        (player_id,),
    ).fetchall()


def batting_totals(db, player_id):
    """2015-2025 totals over the same rows the batting table shows.

    wOBA and wRC+ are deliberately absent: they are league- and park-weighted,
    so no sum or average of season values is meaningful.
    """
    row = db.execute(
        """SELECT COUNT(*)                 AS seasons,
                  SUM(games)               AS games,
                  SUM(plate_appearances)   AS plate_appearances,
                  SUM(home_runs)           AS home_runs,
                  SUM(runs)                AS runs,
                  SUM(rbi)                 AS rbi,
                  SUM(stolen_bases)        AS stolen_bases,
                  SUM(war)                 AS war,
                  CASE WHEN SUM(at_bats) > 0
                       THEN 1.0 * SUM(hits) / SUM(at_bats) END AS batting_avg,
                  CASE WHEN SUM(at_bats + walks + hit_by_pitch + sac_flies) > 0
                       THEN 1.0 * SUM(hits + walks + hit_by_pitch)
                            / SUM(at_bats + walks + hit_by_pitch + sac_flies) END AS obp,
                  CASE WHEN SUM(at_bats) > 0
                       THEN 1.0 * SUM(hits + doubles + 2 * triples + 3 * home_runs)
                            / SUM(at_bats) END AS slg
             FROM batting_stats AS b
            WHERE b.player_id = ? AND """ + SHOWN_BATTING_ROW,
        (player_id,),
    ).fetchone()
    return row if row["seasons"] else None


def pitching_totals(db, player_id):
    """2015-2025 pitching totals. FIP, xFIP and ERA- are absent for the same
    reason as wOBA/wRC+ above. IP comes from summed outs, never ip_display."""
    row = db.execute(
        """SELECT COUNT(*)            AS seasons,
                  SUM(games)          AS games,
                  SUM(games_started)  AS games_started,
                  SUM(outs_recorded)  AS outs_recorded,
                  SUM(strikeouts)     AS strikeouts,
                  SUM(walks)          AS walks,
                  SUM(war)            AS war,
                  CASE WHEN SUM(outs_recorded) > 0
                       THEN 27.0 * SUM(earned_runs) / SUM(outs_recorded) END AS era,
                  CASE WHEN SUM(outs_recorded) > 0
                       THEN 3.0 * SUM(walks + hits_allowed) / SUM(outs_recorded) END AS whip,
                  CASE WHEN SUM(outs_recorded) > 0
                       THEN 27.0 * SUM(strikeouts) / SUM(outs_recorded) END AS k_per_9
             FROM pitching_stats
            WHERE player_id = ?""",
        (player_id,),
    ).fetchone()
    return row if row["seasons"] else None


def recent_notes(db, player_id, limit=3):
    count = db.execute(
        "SELECT COUNT(*) FROM player_notes WHERE player_id = ?", (player_id,)
    ).fetchone()[0]
    notes = db.execute(
        """SELECT note_id, category, body, created_at
             FROM player_notes
            WHERE player_id = ?
            ORDER BY created_at DESC, note_id DESC
            LIMIT ?""",
        (player_id, limit),
    ).fetchall()
    return count, notes


# ---------------------------------------------------------------- compare page

def summary(db, player_id):
    """Seasons played and best single-season combined WAR (raw, not scaled)."""
    seasons = db.execute(
        """SELECT COUNT(*) FROM (
               SELECT b.season_year FROM batting_stats AS b
                WHERE b.player_id = ? AND """ + SHOWN_BATTING_ROW + """
               UNION
               SELECT season_year FROM pitching_stats WHERE player_id = ?
           )""",
        (player_id, player_id),
    ).fetchone()[0]
    best = db.execute(
        "WITH " + COMBINED_WAR_CTE + """
        SELECT season_year, war FROM war
         WHERE player_id = ?
         ORDER BY war DESC, season_year DESC
         LIMIT 1""",
        (player_id,),
    ).fetchone()
    combined = db.execute(
        "WITH " + COMBINED_WAR_CTE + " SELECT SUM(war) FROM war WHERE player_id = ?",
        (player_id,),
    ).fetchone()[0]
    return {"seasons": seasons, "best": best, "combined_war": combined}


# ---------------------------------------------------------------- season page

def batting_row(db, player_id, year):
    row = db.execute(
        """SELECT b.*, t.fangraphs_abbrev,
                  b.plate_appearances >= 3.1 * s.scheduled_games AS qualified
             FROM batting_stats AS b
             JOIN seasons    AS s ON s.season_year = b.season_year
             LEFT JOIN teams AS t ON t.team_id = b.team_id
            WHERE b.player_id = ? AND b.season_year = ? AND """ + SHOWN_BATTING_ROW,
        (player_id, year),
    ).fetchone()
    if row is None:
        return None
    row = dict(row)
    if not row["plate_appearances"]:
        row["woba"] = None      # stored as 0 on PA = 0 rows
    return row


def pitching_row(db, player_id, year):
    return db.execute(
        """SELECT p.*, t.fangraphs_abbrev,
                  p.outs_recorded >= 3 * s.scheduled_games AS qualified
             FROM pitching_stats AS p
             JOIN seasons    AS s ON s.season_year = p.season_year
             LEFT JOIN teams AS t ON t.team_id = p.team_id
            WHERE p.player_id = ? AND p.season_year = ?""",
        (player_id, year),
    ).fetchone()


# RANK() in a CTE over that season's qualified players, filtered to the one
# player in the outer query (SQLite has no QUALIFY). "x IS NULL" first in each
# ORDER BY keeps a missing value from ranking first on an ascending metric.
# *_ties counts players sharing the value, for "tied 12th".
HITTER_RANKS_SQL = """
WITH qualified AS (
    SELECT b.player_id, b.woba, b.wrc_plus, b.war
      FROM batting_stats AS b
      JOIN seasons       AS s ON s.season_year = b.season_year
     WHERE b.season_year = ?
       AND b.plate_appearances >= 3.1 * s.scheduled_games
),
ranked AS (
    SELECT player_id, woba, wrc_plus, war,
           RANK() OVER (ORDER BY woba IS NULL, woba DESC)         AS woba_rank,
           RANK() OVER (ORDER BY wrc_plus IS NULL, wrc_plus DESC) AS wrc_plus_rank,
           RANK() OVER (ORDER BY war IS NULL, war DESC)           AS war_rank,
           COUNT(*) OVER (PARTITION BY woba)                      AS woba_ties,
           COUNT(*) OVER (PARTITION BY wrc_plus)                  AS wrc_plus_ties,
           COUNT(*) OVER (PARTITION BY war)                       AS war_ties,
           COUNT(*) OVER ()                                       AS n
      FROM qualified
)
SELECT * FROM ranked WHERE player_id = ?
"""

PITCHER_RANKS_SQL = """
WITH qualified AS (
    SELECT p.player_id, p.era_minus, p.fip, p.war
      FROM pitching_stats AS p
      JOIN seasons        AS s ON s.season_year = p.season_year
     WHERE p.season_year = ?
       AND p.outs_recorded >= 3 * s.scheduled_games
),
ranked AS (
    SELECT player_id, era_minus, fip, war,
           RANK() OVER (ORDER BY era_minus IS NULL, era_minus ASC) AS era_minus_rank,
           RANK() OVER (ORDER BY fip IS NULL, fip ASC)             AS fip_rank,
           RANK() OVER (ORDER BY war IS NULL, war DESC)            AS war_rank,
           COUNT(*) OVER (PARTITION BY era_minus)                  AS era_minus_ties,
           COUNT(*) OVER (PARTITION BY fip)                        AS fip_ties,
           COUNT(*) OVER (PARTITION BY war)                        AS war_ties,
           COUNT(*) OVER ()                                        AS n
      FROM qualified
)
SELECT * FROM ranked WHERE player_id = ?
"""

HITTER_RANKED = (("woba", "wOBA"), ("wrc_plus", "wRC+"), ("war", "WAR"))
PITCHER_RANKED = (("era_minus", "ERA-"), ("fip", "FIP"), ("war", "WAR"))


def _ranks(db, sql, metrics, player_id, year):
    row = db.execute(sql, (year, player_id)).fetchone()
    if row is None:
        return None
    return [
        {
            "label": label,
            "rank": None if row[key] is None else row[key + "_rank"],
            "tied": row[key] is not None and row[key + "_ties"] > 1,
            "n": row["n"],
        }
        for key, label in metrics
    ]


def hitter_ranks(db, player_id, year):
    """None if the player wasn't a qualified hitter that season."""
    return _ranks(db, HITTER_RANKS_SQL, HITTER_RANKED, player_id, year)


def pitcher_ranks(db, player_id, year):
    return _ranks(db, PITCHER_RANKS_SQL, PITCHER_RANKED, player_id, year)


def qualified_hitter_seasons(db, player_id):
    """Seasons in which the player was a qualified hitter (PA >= 3.1 x games)."""
    return [r[0] for r in db.execute(
        """SELECT b.season_year
             FROM batting_stats AS b
             JOIN seasons       AS s ON s.season_year = b.season_year
            WHERE b.player_id = ?
              AND b.plate_appearances >= 3.1 * s.scheduled_games
            ORDER BY b.season_year""",
        (player_id,),
    ).fetchall()]


def payroll_coverage(db):
    """(team-seasons with payroll, all team-seasons)."""
    return tuple(db.execute(
        "SELECT COUNT(payroll_usd), COUNT(*) FROM team_stats"
    ).fetchone())


def min_pa(scheduled_games):
    """Smallest PA count that satisfies PA >= 3.1 * games (502.2 -> 503)."""
    return math.ceil(PA_PER_GAME * scheduled_games)


def min_outs(scheduled_games):
    return OUTS_PER_GAME * scheduled_games


# ---------------------------------------------------------------- WAR charts

def war_series(db, player_id):
    """(season_year, war, war162) per season, the same numbers Q05 produces."""
    return db.execute(
        "WITH " + COMBINED_WAR_CTE + """
        SELECT w.season_year, w.war,
               w.war * 162.0 / s.scheduled_games AS war162
          FROM war     AS w
          JOIN seasons AS s ON s.season_year = w.season_year
         WHERE w.player_id = ?
         ORDER BY w.season_year""",
        (player_id,),
    ).fetchall()


# Positions with a chart baseline. DH, IF and NULL get none: DH is 1-5
# players a season (mostly one or two bats), IF and NULL are ambiguous.
HITTER_BASELINE_POSITIONS = ("C", "1B", "2B", "3B", "SS", "OF")

# A baseline point is drawn only when at least this many OTHER qualified
# players are in the group that season.
MIN_BASELINE_OTHERS = 5

# Leave-one-out mean of combined WAR/162 per season over a qualified group:
# (sum - own) / (n - 1), where "own" is the player's value if the player is
# in the group that season. Every season in [first, last] gets a row (war162
# NULL when hidden), so the chart leaves a gap instead of bridging it.
# {qualified} is one of the two fixed CTE bodies below, never input.
_BASELINE_SQL = "WITH " + COMBINED_WAR_CTE + """,
qualified AS ({qualified}),
grouped AS (
    SELECT q.season_year,
           SUM(w.war * 162.0 / s.scheduled_games)                      AS total,
           COUNT(*)                                                    AS n,
           MAX(q.player_id = :player_id)                               AS is_member,
           SUM(CASE WHEN q.player_id = :player_id
                    THEN w.war * 162.0 / s.scheduled_games ELSE 0 END) AS own
      FROM qualified AS q
      JOIN war       AS w ON w.player_id = q.player_id AND w.season_year = q.season_year
      JOIN seasons   AS s ON s.season_year = q.season_year
     GROUP BY q.season_year
)
SELECT se.season_year,
       COALESCE(g.n - g.is_member, 0) AS others,
       CASE WHEN g.n - g.is_member >= :min_others
            THEN (g.total - g.own) / (g.n - g.is_member) END AS war162
  FROM seasons AS se
  LEFT JOIN grouped AS g ON g.season_year = se.season_year
 WHERE se.season_year BETWEEN :first AND :last
 ORDER BY se.season_year
"""

# Qualified hitters sharing a primary_position.
HITTER_BASELINE_SQL = _BASELINE_SQL.replace("{qualified}", """
    SELECT b.player_id, b.season_year
      FROM batting_stats AS b
      JOIN seasons       AS s ON s.season_year = b.season_year
      JOIN players       AS p ON p.player_id   = b.player_id
     WHERE b.plate_appearances >= 3.1 * s.scheduled_games
       AND p.primary_position = :position""")

# Qualified pitchers listed at P (qualified by outs; WAR is still combined).
PITCHER_BASELINE_SQL = _BASELINE_SQL.replace("{qualified}", """
    SELECT x.player_id, x.season_year
      FROM pitching_stats AS x
      JOIN seasons        AS s ON s.season_year = x.season_year
      JOIN players        AS p ON p.player_id   = x.player_id
     WHERE x.outs_recorded >= 3 * s.scheduled_games
       AND p.primary_position = 'P'""")


def baseline_kind(position):
    """'hitter', 'pitcher' or None (no baseline for DH, IF, NULL)."""
    if position in HITTER_BASELINE_POSITIONS:
        return "hitter"
    if position == "P":
        return "pitcher"
    return None


def baseline_series(db, player_id, position, first_season, last_season):
    """Leave-one-out rows (season_year, others, war162) for every season in
    range; war162 is NULL where fewer than MIN_BASELINE_OTHERS others qualify.
    None for positions without a baseline."""
    kind = baseline_kind(position)
    if kind is None:
        return None
    params = {"player_id": player_id, "first": first_season, "last": last_season,
              "min_others": MIN_BASELINE_OTHERS}
    if kind == "hitter":
        return db.execute(HITTER_BASELINE_SQL, {**params, "position": position}).fetchall()
    return db.execute(PITCHER_BASELINE_SQL, params).fetchall()


# ---------------------------------------------------------------- team page

def get_team(db, team_id):
    return db.execute(
        """SELECT t.team_id, t.team_name, t.city, t.fangraphs_abbrev, t.first_season,
                  t.last_season, d.division_name, d.league
             FROM teams     AS t
             JOIN divisions AS d ON d.division_id = t.division_id
            WHERE t.team_id = ?""",
        (team_id,),
    ).fetchone()


def team_seasons(db, team_id):
    """One row per season. win_pct, run_differential and pythag_win_pct are
    the generated (rounded) columns: display only. Payroll is compared with
    that season's league average; NULL when payroll isn't loaded."""
    return db.execute(
        """SELECT ts.season_year, ts.wins, ts.losses, ts.win_pct,
                  ts.runs_scored, ts.runs_allowed, ts.run_differential, ts.pythag_win_pct,
                  ts.payroll_usd / 1e6 AS payroll_millions,
                  ts.payroll_usd / (SELECT AVG(x.payroll_usd) FROM team_stats AS x
                                     WHERE x.season_year = ts.season_year) AS payroll_vs_avg,
                  s.is_shortened, s.scheduled_games
             FROM team_stats AS ts
             JOIN seasons    AS s ON s.season_year = ts.season_year
            WHERE ts.team_id = ?
            ORDER BY ts.season_year""",
        (team_id,),
    ).fetchall()


def roster_hitters(db, team_id, season):
    """Single-team batting rows only: a multi-team season is one combined row
    with team_id NULL, so it can't be split across teams."""
    return db.execute(
        """SELECT player_id, full_name, plate_appearances, home_runs, batting_avg, obp, slg,
                  woba, wrc_plus, war
             FROM v_batting_season
            WHERE team_id = ? AND season_year = ? AND is_multi_team = 0
            ORDER BY war DESC, full_name""",
        (team_id, season),
    ).fetchall()


def roster_pitchers(db, team_id, season):
    return db.execute(
        """SELECT p.player_id, pl.full_name, p.games, p.games_started, p.ip_display,
                  p.era, p.fip, p.era_minus, p.war
             FROM pitching_stats AS p
             JOIN players        AS pl ON pl.player_id = p.player_id
            WHERE p.team_id = ? AND p.season_year = ? AND p.is_multi_team = 0
            ORDER BY p.war DESC, pl.full_name""",
        (team_id, season),
    ).fetchall()
