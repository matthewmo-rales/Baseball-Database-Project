-- ============================================================================
-- Baseball Analytics Database — Analytical Queries (Q01–Q20)
-- Run against database/baseball.db (SQLite 3.25+ for window functions;
-- Q17 uses sqrt(), which needs SQLite built with math functions)
-- George Matthew Morales IV
--
-- Verification log (row counts, sample output, checks): queries/VERIFY.md
--
-- Tables and columns used:
--   players         (player_id, full_name, birth_date 'YYYY-MM-DD', primary_position)
--   seasons         (season_year, scheduled_games)
--   teams           (team_id, fangraphs_abbrev, division_id)
--   team_stats      (team_id, season_year, wins, losses,
--                    runs_scored, runs_allowed, payroll_usd)
--   batting_stats / v_batting_season
--                   (player_id, season_year, team_id, is_multi_team,
--                    plate_appearances, hits, home_runs, rbi, walks,
--                    strikeouts, iso, woba, wrc_plus, war)
--   pitching_stats  (player_id, season_year, team_id, is_multi_team,
--                    outs_recorded, earned_runs, strikeouts, fip, war)
--
-- Generated columns used: team_stats.win_pct (Q03), pitching_stats
-- innings_pitched + k_per_9 (Q04), pitching_stats.era (Q19). Q12 computes
-- win% and pythag inline: the generated versions are rounded to 3 decimals,
-- which shifts luck-in-wins by up to ~0.16.
--
-- Position queries use the unambiguous set C/1B/2B/3B/SS/OF (1,362
-- players). NULL, 'IF', 'P' and 'DH' are excluded; LF/CF/RF don't exist.
--
-- 2020 rule used throughout:
--   * Counting-stat comparisons scale by 162.0 / scheduled_games.
--   * Queries sensitive to single-season noise (Q06, Q15, Q17, Q19)
--     exclude 2020 entirely, because scaling 60 games x2.7 amplifies noise.
--
-- Queries with a params CTE: Q05 takes a name (duplicate names return one
-- block per player_id); Q18 takes a player_id. In Flask, the params CTE
-- becomes a bound ? parameter.
--
-- To run one query in DB Browser: highlight it, then Ctrl+Return.
-- ============================================================================


-- =====================================================================
-- TIER 1: JOINs + AGGREGATION
-- =====================================================================

-- Q01: Top 10 hitters by wOBA each season (qualified)
-- Business question: Who were the best overall hitters each year, by the
--   metric front offices actually use instead of batting average?
-- Technique: ROW_NUMBER() partitioned by season in a CTE (SQLite has no
--   QUALIFY); 4-table join; LEFT JOIN so multi-team players aren't dropped.
-- Caveats: Qualified = 3.1 PA per scheduled team game (MLB rule), so the
--   2020 threshold scales automatically. ROW_NUMBER breaks ties arbitrarily.
-- Verified: PASS. 2022 rank 1 = Aaron Judge (NYY, .458 wOBA, 206 wRC+).
WITH ranked AS (
    SELECT
        b.season_year,
        p.full_name AS name,
        COALESCE(t.fangraphs_abbrev, '2+ teams') AS team,
        b.plate_appearances                  AS pa,
        b.woba,
        b.wrc_plus,
        ROW_NUMBER() OVER (
            PARTITION BY b.season_year
            ORDER BY b.woba DESC
        ) AS woba_rank
    FROM v_batting_season AS b
    JOIN players          AS p ON p.player_id   = b.player_id
    JOIN seasons          AS s ON s.season_year = b.season_year
    LEFT JOIN teams       AS t ON t.team_id     = b.team_id
    WHERE b.plate_appearances >= 3.1 * s.scheduled_games
)
SELECT season_year, woba_rank, name, team, pa,
       ROUND(woba, 3) AS woba, wrc_plus
FROM ranked
WHERE woba_rank <= 10
ORDER BY season_year DESC, woba_rank;


-- Q02: Top 5 WAR per position per season
-- Business question: Who were the most valuable players at each position,
--   the unit rosters are actually built around?
-- Technique: RANK() partitioned by two columns (position, season).
-- Caveats: primary_position is career-level, not per-season. Unambiguous
--   set only (C/1B/2B/3B/SS/OF, 1,362 players): excludes NULL, 'IF', 'P',
--   and 'DH' (1-5 players a season). LF/CF/RF don't exist; all outfielders
--   are 'OF'. WAR already includes the positional adjustment. RANK keeps
--   ties, so a group can show >5 rows.
-- Verified: PASS. 2019 C rank 1 = J.T. Realmuto (5.9 WAR).
WITH ranked AS (
    SELECT
        p.primary_position AS pos,
        b.season_year,
        p.full_name AS name,
        b.plate_appearances AS pa,
        b.war,
        RANK() OVER (
            PARTITION BY p.primary_position, b.season_year
            ORDER BY b.war DESC
        ) AS pos_rank
    FROM v_batting_season AS b
    JOIN players          AS p ON p.player_id = b.player_id
    WHERE p.primary_position IS NOT NULL
      AND p.primary_position NOT IN ('IF', 'P', 'DH')
)
SELECT season_year, pos, pos_rank, name, pa, ROUND(war, 1) AS war
FROM ranked
WHERE pos_rank <= 5
ORDER BY season_year DESC, pos, pos_rank;


-- Q03: Team payroll efficiency
-- Business question: Which teams turned payroll into wins most efficiently,
--   judged against their own season's spending environment?
-- Technique: Window AVG over an unaggregated table (league-average payroll
--   per season) mixed with row-level math; RANK within season.
-- Caveats: "Marginal wins" = wins above a replacement-level team
--   (.294 win%, the FanGraphs / B-Ref shared baseline) per $10M of payroll.
--   Uses actual W+L, never 162. Check how the source reports 2020 payroll
--   (prorated vs full-season) before comparing 2020 across seasons.
-- Verified: PASS. TBR ranks 1st in 2019, 2020, 2021 and top 3 in 7 of 11
--   seasons. Source 2020 payroll is prorated (2020 max $128.1M).
WITH t AS (
    SELECT
        ts.season_year,
        tm.fangraphs_abbrev AS team,
        ts.wins,
        ts.losses,
        ts.win_pct                                               AS win_pct,   -- generated column
        ts.wins - 0.294 * (ts.wins + ts.losses)                  AS marginal_wins,
        ts.payroll_usd AS payroll,
        ts.payroll_usd / AVG(1.0 * ts.payroll_usd)
            OVER (PARTITION BY ts.season_year)                   AS payroll_index
    FROM team_stats AS ts
    JOIN teams      AS tm ON tm.team_id = ts.team_id
)
SELECT
    season_year,
    team,
    wins,
    losses,
    ROUND(win_pct, 3)                          AS win_pct,
    ROUND(payroll / 1e6, 1)                    AS payroll_millions,
    ROUND(payroll_index, 2)                    AS payroll_vs_league_avg,
    ROUND(marginal_wins / (payroll / 1e7), 2)  AS marginal_wins_per_10m,
    RANK() OVER (
        PARTITION BY season_year
        ORDER BY marginal_wins / payroll DESC
    )                                          AS efficiency_rank
FROM t
ORDER BY season_year DESC, efficiency_rank;


-- Q04: Pitcher strikeout leaders (min innings, 2020-scaled)
-- Business question: Who were the elite strikeout pitchers each season?
-- Technique: JOIN + window rank; innings derived from outs_recorded
--   (never the base-3 display notation).
-- Caveats: Min 50 IP = 150 outs, scaled by scheduled_games for 2020.
--   K/9 = K * 27 / outs.
-- Verified: PASS. 2019 rank 1 = Gerrit Cole, 326 K, 13.82 K/9.
WITH ranked AS (
    SELECT
        ps.season_year,
        p.full_name AS name,
        ps.strikeouts,
        ps.innings_pitched                            AS ip,     -- generated column
        ps.k_per_9                                    AS k9,     -- generated column
        ps.war,
        RANK() OVER (
            PARTITION BY ps.season_year
            ORDER BY ps.strikeouts DESC
        ) AS k_rank
    FROM pitching_stats AS ps
    JOIN players        AS p ON p.player_id   = ps.player_id
    JOIN seasons        AS s ON s.season_year = ps.season_year
    WHERE ps.outs_recorded >= 150.0 * s.scheduled_games / 162
)
SELECT season_year, k_rank, name, strikeouts,
       ROUND(ip, 1) AS ip, ROUND(k9, 2) AS k9, ROUND(war, 1) AS war
FROM ranked
WHERE k_rank <= 10
ORDER BY season_year DESC, k_rank;


-- =====================================================================
-- TIER 2: WINDOW FUNCTIONS
-- =====================================================================

-- Q05: Career WAR trajectory with 3-year rolling average
-- Business question: Is this player trending up, peaking, or declining?
-- Technique: UNION ALL (batting + pitching WAR, so two-way players are
--   whole); AVG OVER a ROWS frame; LAG.
-- Caveats: WAR scaled to 162 games for 2020. The ROWS frame counts rows,
--   not years, so a skipped season still sits "adjacent". Duplicate names
--   return one block per player_id. Pre-2015 seasons are missing.
-- Verified: PASS. Betts 2015-2025 matches FanGraphs within 0.3 every season.
--   Stored WAR 2015–2025: 4.8, 7.4, 4.6, 10.2, 5.8, 2.7, 3.9, 6.0, 7.6, 4.3, 3.4.
WITH params AS (SELECT 'Mookie Betts' AS target),
war AS (
    SELECT player_id, season_year, SUM(war) AS war
    FROM (
        SELECT player_id, season_year, war FROM batting_stats
        UNION ALL
        SELECT player_id, season_year, war FROM pitching_stats
    )
    GROUP BY player_id, season_year
    HAVING SUM(war) IS NOT NULL
),
scaled AS (
    SELECT w.player_id, w.season_year, w.war,
           w.war * 162.0 / s.scheduled_games AS war162
    FROM war     AS w
    JOIN seasons AS s ON s.season_year = w.season_year
)
SELECT
    p.player_id,
    p.full_name AS name,
    sc.season_year,
    ROUND(sc.war, 1)    AS war,
    ROUND(sc.war162, 1) AS war_per_162,
    ROUND(AVG(sc.war162) OVER (
        PARTITION BY sc.player_id ORDER BY sc.season_year
        ROWS BETWEEN 2 PRECEDING AND CURRENT ROW
    ), 1)               AS rolling_3yr,
    ROUND(sc.war162 - LAG(sc.war162) OVER (
        PARTITION BY sc.player_id ORDER BY sc.season_year
    ), 1)               AS change_vs_prev
FROM scaled  AS sc
JOIN players AS p ON p.player_id = sc.player_id
WHERE p.full_name = (SELECT target FROM params)
ORDER BY p.player_id, sc.season_year;


-- Q06: Biggest year-over-year WAR risers and fallers
-- Business question: Who broke out or collapsed from one season to the
--   next? (Also the closest proxy to injury/recovery without IL data.)
-- Technique: LAG for previous season plus a check that it really was the
--   previous year; two ROW_NUMBERs (asc/desc) to pull both tails in one pass.
-- Caveats: 2020 excluded, so 2019->2021 is not consecutive and is dropped.
--   No playing-time minimum on purpose: injury comebacks show up as risers.
-- Verified: PASS. Judge, Harper, Acuna rows all match FanGraphs within 0.3
--   (Judge 2016->17 +8.7, Harper 2015->16 -7.4, Acuna 2023->24 -8.2).
WITH war AS (
    SELECT player_id, season_year, SUM(war) AS war
    FROM (
        SELECT player_id, season_year, war FROM batting_stats
        UNION ALL
        SELECT player_id, season_year, war FROM pitching_stats
    )
    WHERE season_year <> 2020
    GROUP BY player_id, season_year
    HAVING SUM(war) IS NOT NULL
),
d AS (
    SELECT player_id, season_year, war,
           LAG(war)         OVER (PARTITION BY player_id ORDER BY season_year) AS prev_war,
           LAG(season_year) OVER (PARTITION BY player_id ORDER BY season_year) AS prev_season
    FROM war
),
ranked AS (
    SELECT player_id, prev_season, season_year, prev_war, war,
           war - prev_war AS delta,
           ROW_NUMBER() OVER (ORDER BY war - prev_war DESC) AS up_rk,
           ROW_NUMBER() OVER (ORDER BY war - prev_war ASC)  AS down_rk
    FROM d
    WHERE prev_season = season_year - 1
)
SELECT
    CASE WHEN r.up_rk <= 15 THEN 'Riser' ELSE 'Faller' END AS direction,
    p.full_name AS name,
    r.prev_season,
    r.season_year,
    ROUND(r.prev_war, 1) AS prev_war,
    ROUND(r.war, 1)      AS war,
    ROUND(r.delta, 1)    AS delta
FROM ranked  AS r
JOIN players AS p ON p.player_id = r.player_id
WHERE r.up_rk <= 15 OR r.down_rk <= 15
ORDER BY r.delta DESC;


-- Q07: WAR percentile among position-mates
-- Business question: How good is this player relative to others who play
--   his position that year (not the whole league)?
-- Technique: PERCENT_RANK() and COUNT(*) OVER the same partition
--   (position, season); outer filter on partition size.
-- Caveats: Min 300 PA (scaled for 2020) so part-timers don't distort
--   percentiles. Unambiguous set only (C/1B/2B/3B/SS/OF; no DH, IF, P).
--   Position-seasons with fewer than 10 eligible players are dropped:
--   PERCENT_RANK of a one-player partition is 0.0, and small partitions
--   give coarse percentiles.
-- Verified: PASS. All 66 Q02 rank-1 players sit at 100.0. Smallest
--   partition is 16 players, so the >= 10 floor currently drops nothing.
WITH elig AS (
    SELECT
        b.season_year,
        p.primary_position AS pos,
        p.full_name AS name,
        b.plate_appearances AS pa,
        b.war,
        PERCENT_RANK() OVER (
            PARTITION BY p.primary_position, b.season_year
            ORDER BY b.war
        ) AS pct,
        COUNT(*) OVER (
            PARTITION BY p.primary_position, b.season_year
        ) AS n_in_group
    FROM v_batting_season AS b
    JOIN players          AS p ON p.player_id   = b.player_id
    JOIN seasons          AS s ON s.season_year = b.season_year
    WHERE p.primary_position IS NOT NULL
      AND p.primary_position NOT IN ('IF', 'P', 'DH')
      AND b.plate_appearances >= 300.0 * s.scheduled_games / 162
)
SELECT season_year, pos, name, pa,
       ROUND(war, 1)       AS war,
       ROUND(100 * pct, 1) AS war_percentile,
       n_in_group
FROM elig
WHERE n_in_group >= 10
ORDER BY season_year DESC, pos, war_percentile DESC;


-- Q08: Milestone tracking with cumulative totals
-- Business question: Which players reached 1,000 hits in the 2015–2025
--   window, and in which season did they cross it?
-- Technique: Running SUM() OVER a named WINDOW (UNBOUNDED PRECEDING);
--   "crossed this season" = total >= 1000 AND (total - this season) < 1000.
-- Caveats: Counts 2015+ hits only, not true career totals. A multi-team
--   season is one combined row, which is correct here.
-- Verified: PASS. Freddie Freeman crosses 1,000 (2015+) hits in 2021.
WITH running AS (
    SELECT
        b.player_id,
        b.season_year,
        b.hits,
        SUM(b.hits)      OVER w AS cum_hits,
        SUM(b.home_runs) OVER w AS cum_hr,
        SUM(b.rbi)      OVER w AS cum_rbi
    FROM v_batting_season AS b
    WINDOW w AS (
        PARTITION BY b.player_id ORDER BY b.season_year
        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
    )
)
SELECT p.full_name AS name, r.season_year AS season_reached,
       r.cum_hits, r.cum_hr, r.cum_rbi
FROM running AS r
JOIN players AS p ON p.player_id = r.player_id
WHERE r.cum_hits >= 1000
  AND r.cum_hits - r.hits < 1000
ORDER BY r.season_year, p.full_name;


-- Q09: Consecutive-season streaks of 3+ WAR (per 162)
-- Business question: Who is consistently good, versus a one-year wonder?
-- Technique: Gaps-and-islands. season_year - ROW_NUMBER() is constant
--   across an unbroken run of qualifying seasons, so it works as a group key.
-- Caveats: 2020 scaled to 162 so it doesn't break streaks. A streak that
--   starts in 2015 may extend earlier (window truncation).
-- Verified: PASS. Mike Trout: 2015–2020, 6 seasons, 44.1 WAR.
WITH war AS (
    SELECT player_id, season_year, SUM(war) AS war
    FROM (
        SELECT player_id, season_year, war FROM batting_stats
        UNION ALL
        SELECT player_id, season_year, war FROM pitching_stats
    )
    GROUP BY player_id, season_year
    HAVING SUM(war) IS NOT NULL
),
good AS (
    SELECT w.player_id, w.season_year, w.war
    FROM war     AS w
    JOIN seasons AS s ON s.season_year = w.season_year
    WHERE w.war * 162.0 / s.scheduled_games >= 3.0
),
islands AS (
    SELECT player_id, season_year, war,
           season_year - ROW_NUMBER() OVER (
               PARTITION BY player_id ORDER BY season_year
           ) AS grp
    FROM good
),
streaks AS (
    SELECT player_id,
           MIN(season_year) AS streak_start,
           MAX(season_year) AS streak_end,
           COUNT(*)         AS seasons,
           SUM(war)         AS streak_war
    FROM islands
    GROUP BY player_id, grp
    HAVING COUNT(*) >= 3
)
SELECT p.full_name AS name, st.streak_start, st.streak_end, st.seasons,
       ROUND(st.streak_war, 1) AS streak_war
FROM streaks AS st
JOIN players AS p ON p.player_id = st.player_id
ORDER BY st.seasons DESC, st.streak_war DESC;


-- =====================================================================
-- TIER 3: MULTI-JOIN BUSINESS LOGIC
-- =====================================================================

-- Q10: Birth-cohort productivity
-- Business question: Which birth years produced the most MLB value in
--   2015–2025, and is that talent or just timing?
-- Technique: UNION ALL -> per-player career CTE -> cohort GROUP BY with
--   conditional aggregation (CASE inside SUM).
-- Caveats: NOT a draft class (no draft data). Window truncation is the
--   headline: ages_covered shows which slice of each cohort's career is in
--   the data, so cohorts at peak age during 2015–2025 are favored. Cohorts
--   with fewer than 25 players are hidden.
-- Verified: PASS. Top 3 cohorts are 1992, 1991, 1990 (ages covered
--   23–33, 24–34, 25–35), i.e. at peak age during the window.
WITH war AS (
    SELECT player_id, season_year, SUM(war) AS war
    FROM (
        SELECT player_id, season_year, war FROM batting_stats
        UNION ALL
        SELECT player_id, season_year, war FROM pitching_stats
    )
    GROUP BY player_id, season_year
    HAVING SUM(war) IS NOT NULL
),
career AS (
    SELECT player_id, SUM(war) AS career_war
    FROM war
    GROUP BY player_id
),
cohort AS (
    SELECT CAST(strftime('%Y', p.birth_date) AS INTEGER) AS birth_year,
           c.career_war
    FROM career  AS c
    JOIN players AS p ON p.player_id = c.player_id
    WHERE p.birth_date IS NOT NULL
)
SELECT
    birth_year,
    (2015 - birth_year) || '-' || (2025 - birth_year)        AS ages_covered,
    COUNT(*)                                                 AS players,
    ROUND(SUM(career_war), 1)                                AS total_war,
    ROUND(AVG(career_war), 2)                                AS avg_war_per_player,
    SUM(CASE WHEN career_war >= 20 THEN 1 ELSE 0 END)        AS players_20plus_war
FROM cohort
GROUP BY birth_year
HAVING COUNT(*) >= 25
ORDER BY total_war DESC;


-- Q11: Team cost per WAR (replaces "undervalued players by salary")
-- Business question: How many payroll dollars did each team spend per win
--   of player value, and does roster WAR explain actual wins?
-- Technique: UNION ALL of batting + pitching WAR filtered to single-team
--   rows; aggregate to team-season; join payroll; RANK within season.
-- Caveats: Multi-team player-seasons (team_id NULL) are excluded, so team
--   WAR is understated for trade-heavy teams. No individual salaries exist,
--   so value is team-level only. implied_wins = replacement-level wins
--   (.294 x games) + team WAR, a sanity check against actual wins.
--   Team-seasons with team WAR <= 0 are dropped ($ per WAR is undefined);
--   in this data that is one row, 2025 COL, so 329 of 330 are returned.
-- Verified: PASS. 217 of 329 rows (66%) within 5 wins, 309 (94%) within
--   10; implied_wins averages 1.9 below actual (excluded multi-team WAR).
WITH team_war AS (
    SELECT team_id, season_year, SUM(war) AS war
    FROM (
        SELECT team_id, season_year, war FROM batting_stats  WHERE is_multi_team = 0
        UNION ALL
        SELECT team_id, season_year, war FROM pitching_stats WHERE is_multi_team = 0
    )
    GROUP BY team_id, season_year
)
SELECT
    ts.season_year,
    tm.fangraphs_abbrev                                        AS team,
    ROUND(ts.payroll_usd / 1e6, 1)                             AS payroll_millions,
    ROUND(tw.war, 1)                                       AS team_war,
    ts.wins,
    ROUND(0.294 * (ts.wins + ts.losses) + tw.war, 1)       AS implied_wins,
    ROUND(ts.payroll_usd / 1e6 / NULLIF(tw.war, 0), 2)         AS millions_per_war,
    RANK() OVER (
        PARTITION BY ts.season_year
        ORDER BY ts.payroll_usd / NULLIF(tw.war, 0)
    )                                                      AS cost_rank
FROM team_stats AS ts
JOIN team_war   AS tw ON tw.team_id = ts.team_id AND tw.season_year = ts.season_year
JOIN teams      AS tm ON tm.team_id = ts.team_id
WHERE tw.war > 0
ORDER BY ts.season_year DESC, cost_rank;


-- Q12a: Pythagorean over/under-performers
-- Business question: Which teams won far more or fewer games than their
--   run differential says they should have?
-- Technique: Expected win% = RS^2 / (RS^2 + RA^2), computed inline
--   (exponent 2, same as the generated pythag_win_pct column).
-- Caveats: "Luck" is actual minus expected wins over actual games played.
--   Ranked by luck_per_162 (win% gap x 162) so 2020's 60-game teams are
--   compared on the same scale; luck_wins is the raw count for that season.
--   win% and pythag stay inline: the generated columns are rounded to
--   3 decimals, which moves luck by up to ~0.16 wins.
-- Verified: PASS. 2016 TEX ranks 4th (+13.1 wins); 1st is 2021 SEA (+14.7).
WITH p AS (
    SELECT
        ts.team_id,
        ts.season_year,
        ts.wins,
        ts.losses,
        1.0 * ts.wins / (ts.wins + ts.losses) AS win_pct,
        1.0 * ts.runs_scored * ts.runs_scored
            / (ts.runs_scored * ts.runs_scored + ts.runs_allowed * ts.runs_allowed) AS pyth
    FROM team_stats AS ts
)
SELECT
    p.season_year,
    tm.fangraphs_abbrev                                   AS team,
    p.wins,
    p.losses,
    ROUND(p.pyth * (p.wins + p.losses), 1)            AS expected_wins,
    ROUND((p.win_pct - p.pyth) * (p.wins + p.losses), 1) AS luck_wins,
    ROUND((p.win_pct - p.pyth) * 162, 1)              AS luck_per_162
FROM p
JOIN teams AS tm ON tm.team_id = p.team_id
ORDER BY ABS((p.win_pct - p.pyth) * 162) DESC
LIMIT 20;

-- Q12b: Does Pythagorean luck persist into the next season?
-- Business question: Should a team that out-won its run differential
--   expect to do it again? (Front offices bet on "no".)
-- Technique: LEAD() to pair each team-season with the next; bucketed
--   comparison. Luck is expressed per 162 games so 2020 compares fairly.
-- Caveats: Assumes team_id is stable across renames/relocations; check the
--   Athletics' 2025 rows.
-- Verified: Finding, not the expected result. Lucky (+0.2 next season,
--   n=50) and Neutral (+0.2, n=191) regress to ~0, but the Unlucky bucket
--   persists: -1.5 wins/162 next season (n=59, SE 0.46, ~3.3 SE from 0).
--   Causes (e.g. bullpen quality, roster continuity) are not tested here.
--   Three buckets were compared, so treat one ~3 SE result with that
--   multiple-comparison context in mind.
WITH p AS (
    SELECT team_id, season_year,
           1.0 * wins / (wins + losses) AS win_pct,
           1.0 * runs_scored * runs_scored
               / (runs_scored * runs_scored + runs_allowed * runs_allowed) AS pyth
    FROM team_stats
),
d AS (
    SELECT team_id, season_year,
           (win_pct - pyth) * 162 AS luck162,
           LEAD((win_pct - pyth) * 162) OVER (PARTITION BY team_id ORDER BY season_year) AS next_luck162,
           LEAD(season_year)            OVER (PARTITION BY team_id ORDER BY season_year) AS next_season
    FROM p
)
SELECT
    CASE WHEN luck162 >=  4 THEN '1: Lucky (4+ wins over)'
         WHEN luck162 <= -4 THEN '3: Unlucky (4+ wins under)'
         ELSE                    '2: Neutral' END AS bucket,
    COUNT(*)                     AS team_seasons,
    ROUND(AVG(luck162), 1)       AS avg_luck,
    ROUND(AVG(next_luck162), 1)  AS avg_next_season_luck
FROM d
WHERE next_season = season_year + 1
GROUP BY bucket
ORDER BY bucket;


-- Q13: Does changing teams change a hitter? (replaces mid-season trade impact)
-- Business question: Do hitters who switch teams between seasons improve
--   or decline, beyond what normal year-to-year regression predicts?
-- Technique: Self-join on (player, season, season+1); team-change flag;
--   grouped by prior-performance tier so movers are compared to stayers of
--   similar quality (the regression-to-the-mean control).
-- Caveats: Single-team seasons only (mid-season trades are one combined
--   row, so pre/post splits are impossible). Min 300 PA both seasons,
--   scaled for 2020. Movers are not random: teams choose who to acquire.
-- Verified: PASS. 120+ tier declines for both: movers -19.4, stayers -16.6.
WITH q AS (
    SELECT b.player_id, b.season_year, b.team_id, b.wrc_plus
    FROM v_batting_season AS b
    JOIN seasons          AS s ON s.season_year = b.season_year
    WHERE b.is_multi_team = 0
      AND b.plate_appearances >= 300.0 * s.scheduled_games / 162
),
pairs AS (
    SELECT
        a.wrc_plus AS prev_wrc,
        n.wrc_plus AS next_wrc,
        CASE WHEN a.team_id = n.team_id THEN 'Stayed' ELSE 'Changed teams' END AS grp,
        CASE WHEN a.wrc_plus >= 120 THEN '1: 120+'
             WHEN a.wrc_plus >= 100 THEN '2: 100-119'
             WHEN a.wrc_plus >=  80 THEN '3: 80-99'
             ELSE                        '4: under 80' END AS prior_tier
    FROM q AS a
    JOIN q AS n ON n.player_id = a.player_id
               AND n.season_year = a.season_year + 1
)
SELECT prior_tier, grp,
       COUNT(*)                          AS player_pairs,
       ROUND(AVG(prev_wrc), 1)           AS avg_prev_wrc_plus,
       ROUND(AVG(next_wrc), 1)           AS avg_next_wrc_plus,
       ROUND(AVG(next_wrc - prev_wrc), 1) AS avg_change
FROM pairs
GROUP BY prior_tier, grp
ORDER BY prior_tier, grp;


-- Q14: Position value trend over the decade
-- Business question: Is value concentrating at certain positions, i.e.
--   where is talent scarce or deep?
-- Technique: Aggregate CTE, then windows over the aggregates (position's
--   decade average, LAG for year-over-year).
-- Caveats: PA-weighted WAR per 600 PA. WAR already includes a positional
--   adjustment, so trends show where talent is concentrating, not raw
--   positional value. Career-level position labels. No payroll by position.
--   Unambiguous set only (C/1B/2B/3B/SS/OF). DH excluded: 1-5 players a
--   season, mostly Ortiz/Ohtani, so it measured those two bats, not the slot.
-- Verified: PASS. The positional adjustment is designed to equalize
--   positions, so differences reflect talent concentration in this window:
--   SS (2.60 WAR/600 decade mean) and 3B (2.52) deepest, 1B thinnest (1.61).
WITH pos_season AS (
    SELECT
        p.primary_position                                  AS pos,
        b.season_year,
        COUNT(*)                                            AS players,
        600.0 * SUM(b.war) / SUM(b.plate_appearances)       AS war_per_600
    FROM v_batting_season AS b
    JOIN players          AS p ON p.player_id = b.player_id
    WHERE p.primary_position IS NOT NULL
      AND p.primary_position NOT IN ('IF', 'P', 'DH')
    GROUP BY p.primary_position, b.season_year
)
SELECT
    pos,
    season_year,
    players,
    ROUND(war_per_600, 2) AS war_per_600,
    ROUND(war_per_600 - AVG(war_per_600) OVER (PARTITION BY pos), 2)                    AS vs_decade_avg,
    ROUND(war_per_600 - LAG(war_per_600) OVER (PARTITION BY pos ORDER BY season_year), 2) AS yoy_change
FROM pos_season
ORDER BY pos, season_year;


-- =====================================================================
-- TIER 4: CTEs + PREDICTIVE SETUP
-- =====================================================================

-- Q15: Breakout seasons (leave-one-out career baseline)
-- Business question: Which seasons stood far above a player's normal level?
-- Technique: Leave-one-out average, (career sum - this season) / (n - 1),
--   built from window SUM/COUNT, so the breakout season doesn't inflate
--   its own baseline.
-- Caveats: Descriptive, not predictive: the baseline includes LATER seasons.
--   2020 excluded. Min 3 seasons. Window truncation.
-- Verified: PASS. List includes award years: Harper 2015 (MVP), Arrieta
--   2015 (CY), deGrom 2018 (CY), Bellinger 2019 (MVP), Acuna 2023 (MVP).
WITH war AS (
    SELECT player_id, season_year, SUM(war) AS war
    FROM (
        SELECT player_id, season_year, war FROM batting_stats
        UNION ALL
        SELECT player_id, season_year, war FROM pitching_stats
    )
    WHERE season_year <> 2020
    GROUP BY player_id, season_year
    HAVING SUM(war) IS NOT NULL
),
loo AS (
    SELECT player_id, season_year, war,
           COUNT(*) OVER (PARTITION BY player_id) AS n_seasons,
           (SUM(war) OVER (PARTITION BY player_id) - war)
               / (COUNT(*) OVER (PARTITION BY player_id) - 1) AS other_avg
    FROM war
)
SELECT p.full_name AS name, l.season_year,
       ROUND(l.war, 1)               AS war,
       ROUND(l.other_avg, 1)         AS avg_other_seasons,
       ROUND(l.war - l.other_avg, 1) AS delta,
       l.n_seasons
FROM loo     AS l
JOIN players AS p ON p.player_id = l.player_id
WHERE l.n_seasons >= 3
  AND l.war - l.other_avg >= 2.0
ORDER BY delta DESC
LIMIT 25;


-- Q16: Hitter aging curves by position group (delta method)
-- Business question: At what age do hitters peak and start declining,
--   and does it differ by position? (Contract length and extension timing.)
-- Technique: Age on June 30 (FanGraphs convention); self-join consecutive
--   seasons; harmonic-mean-of-PA weighting (standard in aging research);
--   running SUM of year-to-year changes builds the curve. A 3-age moving
--   average (ROWS 1 PRECEDING / 1 FOLLOWING) smooths single noisy cells;
--   raw and smoothed curves are both shown. A naive average-by-age column
--   is included to show survivorship bias.
-- Caveats: Offense only (wRC+, a rate, so no 2020 scaling). Survivorship
--   bias exists (a pair needs 200+ PA in both seasons, so players who
--   lose their job drop out), but its direction and size are not measured
--   here; the standard correction adds phantom seasons for dropouts.
--   Each curve is anchored at 0 at its youngest age (strictly, the age
--   just before its first cell, since the first row already includes the
--   change into that age), so values are wRC+ change relative to that
--   anchor, not absolute wRC+. The smoothed column uses a 2-cell average
--   at each end of a curve. Age cells with <15
--   pairs are dropped, which can leave gaps. Groups: C, CI (1B/3B),
--   MI (2B/SS), OF; DH, IF, P excluded.
-- Verified: PASS (finding). MI/CI peak at 26-27 (smoothed: MI 27, CI 26).
--   C and OF show no improvement after their first qualifying age, likely
--   selection: the first season of a pair needs 200+ PA, so it skews good.
--   No peak-age claim is made for C or OF. Naive column stays flat at older
--   ages (survivorship contrast holds).
WITH hitters AS (
    SELECT
        b.player_id,
        b.season_year,
        b.plate_appearances AS pa,
        b.wrc_plus,
        b.season_year
          - CAST(strftime('%Y', p.birth_date) AS INTEGER)
          - CASE WHEN strftime('%m-%d', p.birth_date) > '06-30' THEN 1 ELSE 0 END AS age,
        CASE WHEN p.primary_position = 'C'                THEN 'C'
             WHEN p.primary_position IN ('1B', '3B')      THEN 'CI'
             WHEN p.primary_position IN ('2B', 'SS')      THEN 'MI'
             WHEN p.primary_position = 'OF'               THEN 'OF'
        END AS pos_group
    FROM v_batting_season AS b
    JOIN players          AS p ON p.player_id   = b.player_id
    JOIN seasons          AS s ON s.season_year = b.season_year
    WHERE p.birth_date IS NOT NULL
      AND b.plate_appearances >= 200.0 * s.scheduled_games / 162
),
pairs AS (
    SELECT a.pos_group,
           n.age,
           n.wrc_plus - a.wrc_plus         AS delta,
           2.0 * a.pa * n.pa / (a.pa + n.pa) AS w
    FROM hitters AS a
    JOIN hitters AS n ON n.player_id   = a.player_id
                     AND n.season_year = a.season_year + 1
    WHERE a.pos_group IS NOT NULL
),
delta_curve AS (
    SELECT pos_group, age, COUNT(*) AS n_pairs,
           SUM(w * delta) / SUM(w) AS avg_delta
    FROM pairs
    WHERE age BETWEEN 22 AND 38
    GROUP BY pos_group, age
    HAVING COUNT(*) >= 15
),
smoothed AS (
    SELECT pos_group, age, n_pairs, avg_delta,
           AVG(avg_delta) OVER (
               PARTITION BY pos_group ORDER BY age
               ROWS BETWEEN 1 PRECEDING AND 1 FOLLOWING
           ) AS smoothed_change
    FROM delta_curve
),
naive AS (
    SELECT pos_group, age, AVG(wrc_plus) AS naive_wrc_plus
    FROM hitters
    WHERE pos_group IS NOT NULL
    GROUP BY pos_group, age
)
SELECT
    d.pos_group,
    d.age,
    d.n_pairs,
    ROUND(d.avg_delta, 1) AS avg_change_into_age,
    ROUND(SUM(d.avg_delta) OVER (
        PARTITION BY d.pos_group ORDER BY d.age
        ROWS UNBOUNDED PRECEDING
    ), 1)                 AS cumulative_curve,
    ROUND(d.smoothed_change, 1) AS smoothed_change,
    ROUND(SUM(d.smoothed_change) OVER (
        PARTITION BY d.pos_group ORDER BY d.age
        ROWS UNBOUNDED PRECEDING
    ), 1)                 AS smoothed_curve,
    ROUND(n.naive_wrc_plus, 1) AS naive_avg_wrc_plus
FROM smoothed    AS d
LEFT JOIN naive  AS n ON n.pos_group = d.pos_group AND n.age = d.age
ORDER BY d.pos_group, d.age;


-- Q17: Performance consistency (WAR variance)
-- Business question: Among good players, who is reliable and who is
--   volatile? (Risk assessment for trades and multi-year deals.)
-- Technique: Sample variance without STDDEV:
--   (AVG(x^2) - AVG(x)^2) * n / (n - 1); sd_war = sqrt(var_war).
-- Caveats: Hitters only, 300+ PA seasons, 2020 excluded, min 5 seasons,
--   mean WAR >= 2.5. Flip ORDER BY to DESC for the most volatile.
--   sqrt() needs SQLite built with math functions (present in 3.50.4 here;
--   if it errors elsewhere, drop sd_war and order by var_war, same ranking).
--   player_id is shown because full_name is not unique (e.g. Will Smith).
-- Verified: PASS. Tucker has 5 seasons of 300+ PA (excluding 2020), avg
--   WAR 4.7, matches FanGraphs (query: mean 4.69, sd 0.31).
WITH s AS (
    SELECT b.player_id, b.war
    FROM v_batting_season AS b
    WHERE b.season_year <> 2020
      AND b.plate_appearances >= 300
),
agg AS (
    SELECT player_id,
           COUNT(*)  AS n_seasons,
           AVG(war)  AS mean_war,
           (AVG(war * war) - AVG(war) * AVG(war)) * COUNT(*) / (COUNT(*) - 1.0) AS var_war
    FROM s
    GROUP BY player_id
    HAVING COUNT(*) >= 5
)
SELECT a.player_id, p.full_name AS name, a.n_seasons,
       ROUND(a.mean_war, 2)       AS mean_war,
       ROUND(a.var_war, 2)        AS var_war,
       ROUND(sqrt(a.var_war), 2)  AS sd_war
FROM agg     AS a
JOIN players AS p ON p.player_id = a.player_id
WHERE a.mean_war >= 2.5
ORDER BY a.var_war ASC
LIMIT 25;


-- Q18: Comparable-player finder
-- Business question: Which hitter-seasons have the most similar offensive
--   profile to a target? (Comps for projections and trade talks.)
-- Technique: Features made league-relative within each season (so a K% from
--   2015 compares fairly to 2025); standardized squared Euclidean distance,
--   sum of diff^2 / variance, which needs no sqrt; CROSS JOIN target.
-- Caveats: Comps are CROSS-SEASON: any qualified hitter-season 2015–2025
--   can match (features are season-relative, so eras compare fairly).
--   Qualified hitters only. Four features: K%, BB%, ISO, wRC+. Offense
--   only, no defense or speed. Excludes the target's own seasons.
--   Target is keyed on player_id because full_name is not unique. To find
--   an id: SELECT player_id, full_name, birth_date FROM players
--          WHERE full_name LIKE '%' || ? || '%';
-- Verified: PASS. Reviewed the comps, they fit Freeman 2023's hitter
--   profile (K 16.6%, BB 9.9%, ISO .235, 161 wRC+) -> Altuve 2022,
--   Guerrero Jr. 2024, Cabrera 2016, Tucker 2021, Alvarez 2024.
WITH params AS (SELECT 5361 AS target_player_id,   -- Freddie Freeman
                       2023 AS target_season),
q AS (
    SELECT b.player_id, b.season_year,
           1.0 * b.strikeouts / b.plate_appearances AS k_pct,
           1.0 * b.walks      / b.plate_appearances AS bb_pct,
           b.iso,
           b.wrc_plus
    FROM v_batting_season AS b
    JOIN seasons          AS s ON s.season_year = b.season_year
    WHERE b.plate_appearances >= 3.1 * s.scheduled_games
),
rel AS (
    SELECT player_id, season_year, k_pct, bb_pct, iso, wrc_plus,
           k_pct  - AVG(k_pct)  OVER (PARTITION BY season_year) AS k_rel,
           bb_pct - AVG(bb_pct) OVER (PARTITION BY season_year) AS bb_rel,
           iso    - AVG(iso)    OVER (PARTITION BY season_year) AS iso_rel
    FROM q
),
v AS (
    SELECT AVG(k_rel * k_rel)                               AS var_k,
           AVG(bb_rel * bb_rel)                             AS var_bb,
           AVG(iso_rel * iso_rel)                           AS var_iso,
           AVG(1.0 * wrc_plus * wrc_plus) - AVG(wrc_plus) * AVG(wrc_plus) AS var_wrc
    FROM rel
),
target AS (
    SELECT r.*
    FROM rel AS r
    WHERE r.player_id   = (SELECT target_player_id FROM params)
      AND r.season_year = (SELECT target_season    FROM params)
)
SELECT
    p.full_name AS name,
    r.season_year,
    ROUND(100 * r.k_pct, 1)  AS k_pct,
    ROUND(100 * r.bb_pct, 1) AS bb_pct,
    ROUND(r.iso, 3)          AS iso,
    r.wrc_plus,
    ROUND(
        (t.k_rel  - r.k_rel)  * (t.k_rel  - r.k_rel)  / v.var_k
      + (t.bb_rel - r.bb_rel) * (t.bb_rel - r.bb_rel) / v.var_bb
      + (t.iso_rel - r.iso_rel) * (t.iso_rel - r.iso_rel) / v.var_iso
      + (1.0 * t.wrc_plus - r.wrc_plus) * (1.0 * t.wrc_plus - r.wrc_plus) / v.var_wrc
    , 3) AS distance_sq
FROM rel AS r
CROSS JOIN target AS t
CROSS JOIN v
JOIN players AS p ON p.player_id = r.player_id
WHERE r.player_id <> t.player_id
ORDER BY distance_sq
LIMIT 5;


-- Q19 (optional): Is FIP a better predictor of next-season ERA than ERA?
-- Business question: When a pitcher's ERA is far from his FIP, should we
--   expect ERA to move toward FIP next year? (Buy-low / sell-high signal.)
-- Technique: Self-join consecutive seasons; bucket by the ERA-FIP gap;
--   compare mean absolute error of ERA vs FIP as predictors of next ERA.
-- Caveats: Min 100 IP (300 outs) both seasons, 2020 excluded. ERA is
--   computed inline as 27 * ER / outs.
-- Verified: PASS. FIP beats ERA in all buckets; widest gaps in bucket 1
--   (0.83 vs 1.16) and bucket 3 (0.77 vs 1.06).
WITH sp AS (
    SELECT player_id, season_year,
           era,                                  -- generated column
           fip
    FROM pitching_stats
    WHERE season_year <> 2020
      AND outs_recorded >= 300
),
pairs AS (
    SELECT a.era, a.fip, n.era AS next_era, a.era - a.fip AS gap
    FROM sp AS a
    JOIN sp AS n ON n.player_id   = a.player_id
                AND n.season_year = a.season_year + 1
)
SELECT
    CASE WHEN gap <= -0.75 THEN '1: ERA well below FIP (lucky)'
         WHEN gap >=  0.75 THEN '3: ERA well above FIP (unlucky)'
         ELSE                   '2: Within 0.75' END AS bucket,
    COUNT(*)                            AS pitcher_pairs,
    ROUND(AVG(era), 2)                  AS avg_era,
    ROUND(AVG(fip), 2)                  AS avg_fip,
    ROUND(AVG(next_era), 2)             AS avg_next_era,
    ROUND(AVG(ABS(next_era - era)), 2)  AS mae_era_as_predictor,
    ROUND(AVG(ABS(next_era - fip)), 2)  AS mae_fip_as_predictor
FROM pairs
GROUP BY bucket
ORDER BY bucket;


-- =====================================================================
-- ADDITIONAL
-- =====================================================================

-- Q20: Top 10 home run hitters by season
-- Business question: Who led the league in power each year, and how much
--   does the top of the leaderboard move between seasons?
-- Technique: RANK() partitioned by season in a CTE (no QUALIFY).
-- Caveats: Raw counts. 2020 was 60 games, so its totals are not comparable
--   to other seasons (not scaled here). Blank team_id = multi-team season
--   (one combined row). RANK keeps ties, so a season returns more than
--   10 rows when players tie at #10 (6 of 11 seasons; 2020 has 14), and
--   ranks skip after a tie.
-- Verified: PASS. 2017 rank 1 = Giancarlo Stanton, 59 HR (MIA). 121 rows
--   (110 under ROW_NUMBER); the 11 extra are ties at #10: 2017 +1, 2018 +1,
--   2020 +4 (six players tied at 16 HR for 7th), 2021 +2, 2023 +1, 2025 +2.
WITH ranked AS (
    SELECT season_year,
           full_name,
           team_id,
           home_runs,
           RANK() OVER (PARTITION BY season_year ORDER BY home_runs DESC) AS hr_rank
    FROM v_batting_season
)
SELECT season_year, hr_rank, full_name, team_id, home_runs
FROM ranked
WHERE hr_rank <= 10
ORDER BY season_year DESC, hr_rank;
