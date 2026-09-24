-- ============================================================================
-- Baseball Analytics Database — Relational Schema (Phase 1)
-- Target DBMS : SQLite 3.35+ (generated columns require 3.31+)
-- Data source : pybaseball -> FanGraphs season aggregates, 2015-2025
-- Author      : George Matthew Morales IV
-- ============================================================================
-- Design summary
--   7 relations, normalized to 3NF (see design/schema-notes.md for the proof
--   sketch and the three deliberate exceptions).
--   Grain of the two player fact tables is ONE ROW PER PLAYER PER SEASON,
--   which matches what pybaseball.batting_stats(year) / pitching_stats(year)
--   actually return.
-- ============================================================================

PRAGMA foreign_keys = ON;

DROP VIEW  IF EXISTS v_pitching_season;
DROP VIEW  IF EXISTS v_batting_season;
DROP TABLE IF EXISTS team_stats;
DROP TABLE IF EXISTS pitching_stats;
DROP TABLE IF EXISTS batting_stats;
DROP TABLE IF EXISTS players;
DROP TABLE IF EXISTS teams;
DROP TABLE IF EXISTS divisions;
DROP TABLE IF EXISTS seasons;


-- ---------------------------------------------------------------------------
-- 1. divisions
-- ---------------------------------------------------------------------------
-- Exists only to kill a transitive dependency: team_id -> division -> league.
-- Storing `league` directly on teams would leave the schema in 2NF, not 3NF.
-- ---------------------------------------------------------------------------
CREATE TABLE divisions (
    division_id     TEXT    PRIMARY KEY,                 -- 'ALE','ALC','ALW','NLE','NLC','NLW'
    division_name   TEXT    NOT NULL,                    -- 'East','Central','West'
    league          TEXT    NOT NULL
                            CHECK (league IN ('AL','NL')),
    UNIQUE (league, division_name)
);


-- ---------------------------------------------------------------------------
-- 2. teams
-- ---------------------------------------------------------------------------
-- team_id is a stable franchise code, NOT the display abbreviation, so a
-- rename (CLE Indians -> Guardians, 2022) does not orphan ten years of stats.
-- ---------------------------------------------------------------------------
CREATE TABLE teams (
    team_id             TEXT    PRIMARY KEY,             -- 'LAD', 'CLE', 'NYY'
    team_name           TEXT    NOT NULL,                -- current full name
    city                TEXT,
    division_id         TEXT    NOT NULL
                                REFERENCES divisions(division_id)
                                ON UPDATE CASCADE ON DELETE RESTRICT,
    fangraphs_abbrev    TEXT,                            -- abbrev as it appears in pybaseball output
    first_season        INTEGER,
    last_season         INTEGER,                         -- NULL = still active
    CHECK (last_season IS NULL OR last_season >= first_season)
);

CREATE INDEX idx_teams_division ON teams(division_id);


-- ---------------------------------------------------------------------------
-- 3. seasons
-- ---------------------------------------------------------------------------
-- Carries scheduled_games so per-162 rate math survives 2020 (60 games).
-- ---------------------------------------------------------------------------
CREATE TABLE seasons (
    season_year     INTEGER PRIMARY KEY
                            CHECK (season_year BETWEEN 1876 AND 2100),
    scheduled_games INTEGER NOT NULL
                            CHECK (scheduled_games > 0),
    is_shortened    INTEGER NOT NULL DEFAULT 0
                            CHECK (is_shortened IN (0,1)),
    note            TEXT
);


-- ---------------------------------------------------------------------------
-- 4. players
-- ---------------------------------------------------------------------------
-- player_id is the FanGraphs ID (pybaseball column `IDfg`) because that is the
-- key the stat pulls arrive on. mlbam_id / bbref_id are carried so the DB can
-- later join Statcast or Baseball-Reference data without a re-key.
-- ---------------------------------------------------------------------------
CREATE TABLE players (
    player_id           INTEGER PRIMARY KEY,             -- FanGraphs IDfg
    full_name           TEXT    NOT NULL,
    first_name          TEXT,
    last_name           TEXT,
    birth_date          DATE,                            -- from Chadwick register, not FanGraphs
    bats                TEXT    CHECK (bats   IN ('L','R','B')),
    throws              TEXT    CHECK (throws IN ('L','R', 'B')),
    primary_position    TEXT    CHECK (primary_position IN
                                ('C','1B','2B','3B','SS','LF','CF','RF','DH','SP','RP','P','OF','IF')),
    debut_year          INTEGER,
    mlbam_id            INTEGER UNIQUE,
    bbref_id            TEXT    UNIQUE
);

CREATE INDEX idx_players_name ON players(last_name, first_name);


-- ---------------------------------------------------------------------------
-- 5. batting_stats
-- ---------------------------------------------------------------------------
-- Grain: one row per player per season (FanGraphs season aggregate).
-- team_id IS NULL when the player appeared for 2+ clubs that year; FanGraphs
-- reports those as "- - -". is_multi_team makes that explicit rather than
-- forcing every query to reason about a NULL.
--
-- Rate stats that are a pure function of the counting stats in this row are
-- GENERATED, not stored -- that is how the table stays in 3NF while still
-- exposing AVG/OBP/SLG/OPS to queries.
-- Context-dependent metrics (wOBA, wRC+, WAR) ARE stored: they depend on
-- league-wide run environment and park factors, not on this row, so they are
-- not derivable and create no update anomaly.
-- ---------------------------------------------------------------------------
CREATE TABLE batting_stats (
    batting_id          INTEGER PRIMARY KEY,
    player_id           INTEGER NOT NULL
                                REFERENCES players(player_id)
                                ON UPDATE CASCADE ON DELETE CASCADE,
    season_year         INTEGER NOT NULL
                                REFERENCES seasons(season_year)
                                ON UPDATE CASCADE ON DELETE RESTRICT,
    team_id             TEXT    REFERENCES teams(team_id)
                                ON UPDATE CASCADE ON DELETE SET NULL,
    is_multi_team       INTEGER NOT NULL DEFAULT 0
                                CHECK (is_multi_team IN (0,1)),

    -- counting stats (the stored, non-derivable facts)
    games               INTEGER CHECK (games            >= 0),
    plate_appearances   INTEGER CHECK (plate_appearances>= 0),
    at_bats             INTEGER CHECK (at_bats          >= 0),
    hits                INTEGER CHECK (hits             >= 0),
    doubles             INTEGER CHECK (doubles          >= 0),
    triples             INTEGER CHECK (triples          >= 0),
    home_runs           INTEGER CHECK (home_runs        >= 0),
    runs                INTEGER CHECK (runs             >= 0),
    rbi                 INTEGER CHECK (rbi              >= 0),
    walks               INTEGER CHECK (walks            >= 0),
    intentional_walks   INTEGER CHECK (intentional_walks>= 0),
    hit_by_pitch        INTEGER CHECK (hit_by_pitch     >= 0),
    strikeouts          INTEGER CHECK (strikeouts       >= 0),
    sac_flies           INTEGER CHECK (sac_flies        >= 0),
    sac_hits            INTEGER CHECK (sac_hits         >= 0),
    stolen_bases        INTEGER CHECK (stolen_bases     >= 0),
    caught_stealing     INTEGER CHECK (caught_stealing  >= 0),

    -- context-dependent advanced metrics (stored: not derivable in-row)
    woba                REAL,
    wrc_plus            INTEGER,
    war                 REAL,
    off_runs            REAL,                            -- FanGraphs Off
    def_runs            REAL,                            -- FanGraphs Def
    bsr                 REAL,                            -- FanGraphs BsR

    -- derived rate stats (generated: no storage, no update anomaly)
    total_bases         INTEGER GENERATED ALWAYS AS
                        (hits + doubles + 2*triples + 3*home_runs) VIRTUAL,
    batting_avg         REAL GENERATED ALWAYS AS
                        (CASE WHEN at_bats > 0
                              THEN ROUND(CAST(hits AS REAL) / at_bats, 3) END) VIRTUAL,
    obp                 REAL GENERATED ALWAYS AS
                        (CASE WHEN (at_bats + walks + hit_by_pitch + sac_flies) > 0
                              THEN ROUND(CAST(hits + walks + hit_by_pitch AS REAL)
                                   / (at_bats + walks + hit_by_pitch + sac_flies), 3) END) VIRTUAL,
    slg                 REAL GENERATED ALWAYS AS
                        (CASE WHEN at_bats > 0
                              THEN ROUND(CAST(hits + doubles + 2*triples + 3*home_runs AS REAL)
                                   / at_bats, 3) END) VIRTUAL,
    ops                 REAL GENERATED ALWAYS AS
                        (CASE WHEN at_bats > 0 AND (at_bats + walks + hit_by_pitch + sac_flies) > 0
                              THEN ROUND(
                                   CAST(hits + walks + hit_by_pitch AS REAL)
                                     / (at_bats + walks + hit_by_pitch + sac_flies)
                                 + CAST(hits + doubles + 2*triples + 3*home_runs AS REAL)
                                     / at_bats, 3) END) VIRTUAL,
    iso                 REAL GENERATED ALWAYS AS
                        (CASE WHEN at_bats > 0
                              THEN ROUND(CAST(doubles + 2*triples + 3*home_runs AS REAL)
                                   / at_bats, 3) END) VIRTUAL,
    bb_pct              REAL GENERATED ALWAYS AS
                        (CASE WHEN plate_appearances > 0
                              THEN ROUND(100.0 * walks / plate_appearances, 1) END) VIRTUAL,
    k_pct               REAL GENERATED ALWAYS AS
                        (CASE WHEN plate_appearances > 0
                              THEN ROUND(100.0 * strikeouts / plate_appearances, 1) END) VIRTUAL,

    UNIQUE (player_id, season_year),
    CHECK (hits <= at_bats),
    CHECK (doubles + triples + home_runs <= hits),
    CHECK (at_bats <= plate_appearances),
    CHECK (is_multi_team = 1 OR team_id IS NOT NULL)
);

CREATE INDEX idx_batting_season      ON batting_stats(season_year);
CREATE INDEX idx_batting_player      ON batting_stats(player_id);
CREATE INDEX idx_batting_team_season ON batting_stats(team_id, season_year);
CREATE INDEX idx_batting_war         ON batting_stats(season_year, war DESC);


-- ---------------------------------------------------------------------------
-- 6. pitching_stats
-- ---------------------------------------------------------------------------
-- IMPORTANT: innings are stored as outs_recorded (INTEGER), never as the
-- "180.1" display notation. 180.1 means 180 and 1/3 innings; summing that
-- column as a float silently produces wrong ERA, WHIP and K/9. Everything
-- rate-based is generated off outs_recorded.
-- ---------------------------------------------------------------------------
CREATE TABLE pitching_stats (
    pitching_id         INTEGER PRIMARY KEY,
    player_id           INTEGER NOT NULL
                                REFERENCES players(player_id)
                                ON UPDATE CASCADE ON DELETE CASCADE,
    season_year         INTEGER NOT NULL
                                REFERENCES seasons(season_year)
                                ON UPDATE CASCADE ON DELETE RESTRICT,
    team_id             TEXT    REFERENCES teams(team_id)
                                ON UPDATE CASCADE ON DELETE SET NULL,
    is_multi_team       INTEGER NOT NULL DEFAULT 0
                                CHECK (is_multi_team IN (0,1)),

    -- counting stats
    games               INTEGER CHECK (games         >= 0),
    games_started       INTEGER CHECK (games_started >= 0),
    wins                INTEGER CHECK (wins          >= 0),
    losses              INTEGER CHECK (losses        >= 0),
    saves               INTEGER CHECK (saves         >= 0),
    outs_recorded       INTEGER NOT NULL
                                CHECK (outs_recorded >= 0),   -- canonical innings unit
    batters_faced       INTEGER CHECK (batters_faced >= 0),
    hits_allowed        INTEGER CHECK (hits_allowed  >= 0),
    runs_allowed        INTEGER CHECK (runs_allowed  >= 0),
    earned_runs         INTEGER CHECK (earned_runs   >= 0),
    home_runs_allowed   INTEGER CHECK (home_runs_allowed >= 0),
    walks               INTEGER CHECK (walks         >= 0),
    intentional_walks   INTEGER CHECK (intentional_walks >= 0),
    hit_batters         INTEGER CHECK (hit_batters   >= 0),
    strikeouts          INTEGER CHECK (strikeouts    >= 0),

    -- context-dependent advanced metrics (stored)
    fip                 REAL,
    xfip                REAL,
    era_minus           REAL,                            -- FanGraphs native; 100 = league average, lower is better
    fip_minus           REAL,
    war                 REAL,
    lob_pct             REAL,
    babip_against       REAL,

    -- derived rate stats (generated)
    -- TRUE decimal innings -- use this one for all arithmetic.
    innings_pitched     REAL    GENERATED ALWAYS AS
                        (ROUND(outs_recorded / 3.0, 2)) VIRTUAL,
    -- Baseball display notation (60.1 = 60 and 1/3). NEVER sum or average this.
    ip_display          REAL    GENERATED ALWAYS AS
                        (outs_recorded / 3 + (outs_recorded % 3) / 10.0) VIRTUAL,
    era                 REAL    GENERATED ALWAYS AS
                        (CASE WHEN outs_recorded > 0
                              THEN ROUND(earned_runs * 27.0 / outs_recorded, 2) END) VIRTUAL,
    whip                REAL    GENERATED ALWAYS AS
                        (CASE WHEN outs_recorded > 0
                              THEN ROUND((walks + hits_allowed) * 3.0 / outs_recorded, 2) END) VIRTUAL,
    k_per_9             REAL    GENERATED ALWAYS AS
                        (CASE WHEN outs_recorded > 0
                              THEN ROUND(strikeouts * 27.0 / outs_recorded, 2) END) VIRTUAL,
    bb_per_9            REAL    GENERATED ALWAYS AS
                        (CASE WHEN outs_recorded > 0
                              THEN ROUND(walks * 27.0 / outs_recorded, 2) END) VIRTUAL,
    hr_per_9            REAL    GENERATED ALWAYS AS
                        (CASE WHEN outs_recorded > 0
                              THEN ROUND(home_runs_allowed * 27.0 / outs_recorded, 2) END) VIRTUAL,
    k_bb_ratio          REAL    GENERATED ALWAYS AS
                        (CASE WHEN walks > 0
                              THEN ROUND(CAST(strikeouts AS REAL) / walks, 2) END) VIRTUAL,
    -- ERA+ is the Baseball-Reference scale; FanGraphs ships ERA-. They are
    -- reciprocal by construction, so ERA+ is derived rather than re-sourced.
    era_plus            REAL    GENERATED ALWAYS AS
                        (CASE WHEN era_minus > 0
                              THEN ROUND(10000.0 / era_minus, 0) END) VIRTUAL,

    UNIQUE (player_id, season_year),
    CHECK (games_started <= games),
    CHECK (earned_runs <= runs_allowed),
    CHECK (home_runs_allowed <= hits_allowed),
    CHECK (is_multi_team = 1 OR team_id IS NOT NULL)
);

CREATE INDEX idx_pitching_season      ON pitching_stats(season_year);
CREATE INDEX idx_pitching_player      ON pitching_stats(player_id);
CREATE INDEX idx_pitching_team_season ON pitching_stats(team_id, season_year);
CREATE INDEX idx_pitching_war         ON pitching_stats(season_year, war DESC);


-- ---------------------------------------------------------------------------
-- 7. team_stats
-- ---------------------------------------------------------------------------
-- Grain: one row per team per season. payroll_usd is nullable because it is
-- NOT available from pybaseball and must be loaded from a separate source
-- (Spotrac / Cot's Contracts) -- 30 teams x 11 seasons = 330 rows.
-- ---------------------------------------------------------------------------
CREATE TABLE team_stats (
    team_stat_id        INTEGER PRIMARY KEY,
    team_id             TEXT    NOT NULL
                                REFERENCES teams(team_id)
                                ON UPDATE CASCADE ON DELETE CASCADE,
    season_year         INTEGER NOT NULL
                                REFERENCES seasons(season_year)
                                ON UPDATE CASCADE ON DELETE RESTRICT,
    games_played        INTEGER CHECK (games_played >= 0),
    wins                INTEGER CHECK (wins   >= 0),
    losses              INTEGER CHECK (losses >= 0),
    runs_scored         INTEGER CHECK (runs_scored  >= 0),
    runs_allowed        INTEGER CHECK (runs_allowed >= 0),
    payroll_usd         INTEGER CHECK (payroll_usd IS NULL OR payroll_usd > 0),
    playoff_result      TEXT    CHECK (playoff_result IN
                                ('None','WC','DS','CS','WS','WS_Champion')),

    win_pct             REAL    GENERATED ALWAYS AS
                        (CASE WHEN (wins + losses) > 0
                              THEN ROUND(CAST(wins AS REAL) / (wins + losses), 3) END) VIRTUAL,
    run_differential    INTEGER GENERATED ALWAYS AS
                        (runs_scored - runs_allowed) VIRTUAL,
    -- Pythagorean expectation, exponent 2 (Bill James' original form).
    pythag_win_pct      REAL    GENERATED ALWAYS AS
                        (CASE WHEN (runs_scored*runs_scored + runs_allowed*runs_allowed) > 0
                              THEN ROUND(CAST(runs_scored*runs_scored AS REAL)
                                   / (runs_scored*runs_scored + runs_allowed*runs_allowed), 3) END) VIRTUAL,

    UNIQUE (team_id, season_year)
);

CREATE INDEX idx_team_stats_season ON team_stats(season_year);


-- ---------------------------------------------------------------------------
-- Convenience views (the join every analytical query would otherwise repeat)
-- ---------------------------------------------------------------------------
CREATE VIEW v_batting_season AS
SELECT  b.batting_id, b.player_id, p.full_name, p.birth_date, p.bats,
        p.primary_position, b.season_year,
        b.team_id, t.team_name, d.division_name, d.league,
        b.is_multi_team, b.games, b.plate_appearances, b.at_bats, b.hits,
        b.doubles, b.triples, b.home_runs, b.runs, b.rbi, b.walks,
        b.strikeouts, b.stolen_bases,
        b.batting_avg, b.obp, b.slg, b.ops, b.iso,
        b.woba, b.wrc_plus, b.war
FROM        batting_stats b
JOIN        players   p ON p.player_id   = b.player_id
LEFT JOIN   teams     t ON t.team_id     = b.team_id
LEFT JOIN   divisions d ON d.division_id = t.division_id
WHERE b.plate_appearances > 0;

CREATE VIEW v_pitching_season AS
SELECT  s.pitching_id, s.player_id, p.full_name, p.throws, s.season_year,
        s.team_id, t.team_name, d.division_name, d.league,
        s.is_multi_team, s.games, s.games_started, s.innings_pitched,
        s.strikeouts, s.walks, s.hits_allowed, s.earned_runs,
        s.era, s.whip, s.k_per_9, s.bb_per_9, s.fip, s.xfip,
        s.era_minus, s.era_plus, s.war
FROM        pitching_stats s
JOIN        players   p ON p.player_id   = s.player_id
LEFT JOIN   teams     t ON t.team_id     = s.team_id
LEFT JOIN   divisions d ON d.division_id = t.division_id;
