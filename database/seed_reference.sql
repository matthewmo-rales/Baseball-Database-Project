-- ============================================================================
-- Reference data seed: divisions + teams
-- Run AFTER design/schema.sql, BEFORE any stat loading.
--
--   sqlite3 database/baseball.db < design/schema.sql
--   sqlite3 database/baseball.db < database/seed_reference.sql
--
-- Division alignment is stable across 2015-2025 (no realignment in this
-- window), so these 36 rows are a one-time manual load.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------------
-- divisions
-- ---------------------------------------------------------------------------
INSERT INTO divisions (division_id, division_name, league) VALUES
    ('ALE', 'East',    'AL'),
    ('ALC', 'Central', 'AL'),
    ('ALW', 'West',    'AL'),
    ('NLE', 'East',    'NL'),
    ('NLC', 'Central', 'NL'),
    ('NLW', 'West',    'NL');

-- ---------------------------------------------------------------------------
-- teams
-- ---------------------------------------------------------------------------
-- team_id is the stable franchise code. fangraphs_abbrev is what appears in
-- the pybaseball `Team` column -- VERIFY these against a real pull before
-- trusting the join (see note at bottom of file).
--
-- team_name holds CURRENT identity, per design decision 3.4 in schema-notes.md:
--   - CLE was "Cleveland Indians" through 2021, "Guardians" from 2022
--   - OAK was "Oakland Athletics" through 2024, "Athletics" from 2025
-- Queries on 2015-2021 data will therefore show the modern names.
-- ---------------------------------------------------------------------------
INSERT INTO teams (team_id, team_name, city, division_id, fangraphs_abbrev, first_season, last_season) VALUES
    -- AL East
    ('BAL', 'Baltimore Orioles',     'Baltimore',      'ALE', 'BAL', 1901, NULL),
    ('BOS', 'Boston Red Sox',        'Boston',         'ALE', 'BOS', 1901, NULL),
    ('NYY', 'New York Yankees',      'New York',       'ALE', 'NYY', 1903, NULL),
    ('TBR', 'Tampa Bay Rays',        'St. Petersburg', 'ALE', 'TBR', 1998, NULL),
    ('TOR', 'Toronto Blue Jays',     'Toronto',        'ALE', 'TOR', 1977, NULL),
    -- AL Central
    ('CHW', 'Chicago White Sox',     'Chicago',        'ALC', 'CHW', 1901, NULL),
    ('CLE', 'Cleveland Guardians',   'Cleveland',      'ALC', 'CLE', 1901, NULL),
    ('DET', 'Detroit Tigers',        'Detroit',        'ALC', 'DET', 1901, NULL),
    ('KCR', 'Kansas City Royals',    'Kansas City',    'ALC', 'KCR', 1969, NULL),
    ('MIN', 'Minnesota Twins',       'Minneapolis',    'ALC', 'MIN', 1961, NULL),
    -- AL West
    ('HOU', 'Houston Astros',        'Houston',        'ALW', 'HOU', 1962, NULL),
    ('LAA', 'Los Angeles Angels',    'Anaheim',        'ALW', 'LAA', 1961, NULL),
    ('OAK', 'Athletics',             'West Sacramento','ALW', 'OAK', 1901, NULL),
    ('SEA', 'Seattle Mariners',      'Seattle',        'ALW', 'SEA', 1977, NULL),
    ('TEX', 'Texas Rangers',         'Arlington',      'ALW', 'TEX', 1961, NULL),
    -- NL East
    ('ATL', 'Atlanta Braves',        'Atlanta',        'NLE', 'ATL', 1871, NULL),
    ('MIA', 'Miami Marlins',         'Miami',          'NLE', 'MIA', 1993, NULL),
    ('NYM', 'New York Mets',         'New York',       'NLE', 'NYM', 1962, NULL),
    ('PHI', 'Philadelphia Phillies', 'Philadelphia',   'NLE', 'PHI', 1883, NULL),
    ('WSN', 'Washington Nationals',  'Washington',     'NLE', 'WSN', 1969, NULL),
    -- NL Central
    ('CHC', 'Chicago Cubs',          'Chicago',        'NLC', 'CHC', 1876, NULL),
    ('CIN', 'Cincinnati Reds',       'Cincinnati',     'NLC', 'CIN', 1882, NULL),
    ('MIL', 'Milwaukee Brewers',     'Milwaukee',      'NLC', 'MIL', 1969, NULL),
    ('PIT', 'Pittsburgh Pirates',    'Pittsburgh',     'NLC', 'PIT', 1882, NULL),
    ('STL', 'St. Louis Cardinals',   'St. Louis',      'NLC', 'STL', 1882, NULL),
    -- NL West
    ('ARI', 'Arizona Diamondbacks',  'Phoenix',        'NLW', 'ARI', 1998, NULL),
    ('COL', 'Colorado Rockies',      'Denver',         'NLW', 'COL', 1993, NULL),
    ('LAD', 'Los Angeles Dodgers',   'Los Angeles',    'NLW', 'LAD', 1884, NULL),
    ('SDP', 'San Diego Padres',      'San Diego',      'NLW', 'SDP', 1969, NULL),
    ('SFG', 'San Francisco Giants',  'San Francisco',  'NLW', 'SFG', 1883, NULL);

-- ---------------------------------------------------------------------------
-- seasons
-- ---------------------------------------------------------------------------
INSERT INTO seasons (season_year, scheduled_games, is_shortened, note) VALUES
    (2015, 162, 0, NULL),
    (2016, 162, 0, NULL),
    (2017, 162, 0, NULL),
    (2018, 162, 0, NULL),
    (2019, 162, 0, NULL),
    (2020,  60, 1, 'COVID-19 shortened season'),
    (2021, 162, 0, NULL),
    (2022, 162, 0, NULL),
    (2023, 162, 0, NULL),
    (2024, 162, 0, NULL),
    (2025, 162, 0, NULL);

-- ============================================================================
-- VERIFY BEFORE TRUSTING: FanGraphs abbreviations
-- ============================================================================
-- The `fangraphs_abbrev` values above are the conventional forms, but the
-- exact strings in the pybaseball `Team` column are worth confirming rather
-- than assuming -- KCR/KC, SDP/SD, SFG/SF, TBR/TB, WSN/WSH and CHW/CWS are
-- all plausible variants depending on the source endpoint.
--
-- Run this once in Python before writing the loader:
--
--     from pybaseball import batting_stats
--     df = batting_stats(2023, qual=0, ind=1)
--     print(sorted(df['Team'].unique()))
--
-- You should get 31 values: 30 clubs plus "- - -" for multi-team players.
-- Fix any mismatches in this file, then reload it.
-- ============================================================================
