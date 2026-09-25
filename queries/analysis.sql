-- ============================================================================
-- Baseball Analytics Database — Analytical Queries
-- Run against database/baseball.db (SQLite)
-- George Matthew Morales IV
-- ============================================================================


-- ============================================================================
-- TIER 1 — JOINs and aggregation
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Query 1: Top 10 home run hitters by season, 2015–2025
--
-- Question: who led the league in power each year, and how much does the top
-- of the leaderboard move between seasons?
-- Note: 2020 was a 60-game season, so its totals are not comparable to the
--       others. Blank team = player appeared for multiple clubs that year.
-- ----------------------------------------------------------------------------
WITH ranked AS (
    SELECT season_year,
           full_name,
           team_id,
           home_runs,
           ROW_NUMBER() OVER (PARTITION BY season_year ORDER BY home_runs DESC) AS hr_rank
    FROM v_batting_season
)
SELECT season_year, hr_rank, full_name, team_id, home_runs
FROM ranked
WHERE hr_rank <= 10
ORDER BY season_year DESC, hr_rank;


-- ----------------------------------------------------------------------------
-- Query 2: Top 10 position players by WAR, by season
--
-- Question: who were the most valuable hitters each year? WAR captures total
-- contribution — hitting, baserunning, defense and position — where a home
-- run leaderboard only captures power.
-- Technique: same window pattern as Query 1 with a different metric.
-- Note: batting WAR only. Pitcher WAR lives in pitching_stats; see Query N
--       for the combined leaderboard.
-- ----------------------------------------------------------------------------
WITH ranked AS (
    SELECT season_year,
           full_name,
           team_id,
           war,
           ROW_NUMBER() OVER (PARTITION BY season_year ORDER BY war DESC) AS war_rank
    FROM v_batting_season
)
SELECT season_year, war_rank, full_name, team_id, war
FROM ranked
WHERE war_rank <= 10
ORDER BY season_year DESC, war_rank;