# Schema Design Notes — Baseball Analytics Database
- **Source:** FanGraphs JSON leaderboard API, 2015–2025
- **Relations:** 8 (7 loaded, 1 app-written) · **Normal form:** BCNF, with three documented exceptions
- **Status:** loaded and validated -  4,019 players, 15,521 batting and 8,968 pitching season rows, 330 team-seasons, 0 notes after a fresh load; every AVG/OBP/SLG/IP/ERA reconciles against source and `foreign_key_check` is clean

---

## 1. Grain

The single most important decision, because it determines what every downstream query means.

| Relation | Grain | Rows |
|---|---|---|
| `divisions` | one row per division | 6 |
| `teams` | one row per franchise | 30 |
| `seasons` | one row per season | 11 |
| `players` | one row per player | 4,019 |
| `batting_stats` | **one row per player per season** | 15,521 |
| `pitching_stats` | **one row per player per season** | 8,968 |
| `team_stats` | one row per team per season | 330 |
| `player_notes` | one row per note (app-written, §3.11) | 0 after a fresh load |

The FanGraphs leaderboard API returns one row per player per season, already
aggregated across teams. The schema matches that grain rather than inventing a
stint-level grain the source cannot fill. `UNIQUE (player_id, season_year)` makes
this contract enforceable rather than aspirational.

**Consequence:** a player traded mid-season has one row with `team_id IS NULL`
and `is_multi_team = 1` — the source labels these `2 Tms` through `5 Tms`, and
they run 120–140 batters a season. Any "stats by team" query must filter
`is_multi_team = 0` or it will silently undercount. This is called out here
because it is the mistake most likely to produce plausible-but-wrong query
results in Phase 3.

---

## 2. Normalization analysis

### Functional dependencies, by relation

**`divisions`** — `division_id → division_name, league`; also
`{league, division_name} → division_id`. Two candidate keys, both determinants
are superkeys. **BCNF.**

**`teams`** — `team_id →` everything else. Single candidate key. **BCNF.**

> This relation is the reason `divisions` exists. The obvious design puts
> `league` and `division` directly on `teams`, which creates the transitive
> dependency `team_id → division → league` — a textbook **3NF violation**.
> The anomaly is real, not theoretical: correcting a division's league
> assignment would require touching every team row in that division, and
> nothing structurally prevents 'NL East' and 'AL' appearing on the same row.
> Extracting `divisions` removes it.

**`seasons`** — `season_year →` everything else. **BCNF.**

**`players`** — `player_id →` everything else; `mlbam_id →` and `bbref_id →`
likewise (three candidate keys, all declared). **BCNF.**

**`batting_stats` / `pitching_stats`** — candidate keys `{batting_id}` and
`{player_id, season_year}`. Every attribute is fully dependent on the composite
key; none depends on another non-key attribute. **BCNF.**

> This is only true because of the generated-column decision in §3.2. Storing
> `batting_avg` as a plain column would introduce
> `{hits, at_bats} → batting_avg` — a dependency between non-key attributes,
> i.e. a 3NF violation, and the source of a genuine update anomaly (correct a
> hit total, and the stored average is now a lie).

**`team_stats`** — candidate keys `{team_stat_id}` and `{team_id, season_year}`.
**BCNF.**

**`player_notes`** — `note_id →` everything else. The only candidate key: a
player can have any number of notes, in any category, even with identical
text, so no natural key exists. **BCNF.** Design rationale in §3.11.

### Why surrogate keys alongside natural keys

Each fact table has an `INTEGER PRIMARY KEY` surrogate *and* a `UNIQUE`
constraint on its natural key. The surrogate keeps the Flask app's URLs and FK
references short and stable; the `UNIQUE` constraint is what actually enforces
the grain and makes the loader idempotent
(`INSERT ... ON CONFLICT (player_id, season_year) DO UPDATE`). Dropping either
one loses something: without the surrogate, re-keying is painful; without the
natural-key constraint, a second load run silently doubles the data.

---

## 3. Key design decisions

### 3.1 Innings pitched are stored as **outs**, never as `180.1`

Baseball writes 180⅓ innings as `180.1`. That notation is base-3 masquerading
as decimal. `SUM(innings_pitched)` over `180.1 + 180.2` returns `360.3` where
the answer is 361 — and `earned_runs * 9 / 180.1` is wrong by about 0.2 runs of
ERA. The bug is quiet: every number still looks like a plausible ERA.

`pitching_stats.outs_recorded INTEGER` is the canonical unit. Two generated
columns sit on top:

- `innings_pitched` — true decimal (`outs / 3.0`), **use this for all arithmetic**
- `ip_display` — conventional notation (`outs/3 + (outs%3)/10`), **display only, never aggregate**

Loader conversion: `outs = round(ip_float) * 3 + round((ip_float % 1) * 10)`.

### 3.2 Derived rates are generated columns; context-dependent metrics are stored

Two categories of statistic, handled differently on principle:

| | Examples | Treatment | Why |
|---|---|---|---|
| **Derivable in-row** | AVG, OBP, SLG, OPS, ISO, ERA, WHIP, K/9, win%, run differential | `GENERATED ALWAYS AS ... VIRTUAL` | A pure function of columns in the same row. Storing it duplicates information and can drift from its inputs. |
| **Context-dependent** | WAR, wOBA, wRC+, FIP, xFIP, ERA-, BsR | Stored `REAL` | Depends on league-wide run environment, park factors and positional adjustments — data this database does not hold. Not derivable, therefore no redundancy and no violation. |

`VIRTUAL` (not `STORED`) means zero disk cost, computed on read. At this data
volume the cost is negligible and the correctness guarantee is absolute.

This split is also the cleanest interview answer to *"why did you normalize it
that way?"* — the line isn't "normalize everything," it's **derivable stays
derived, imported stays stored.**

### 3.3 ERA+ is derived from ERA-, not re-sourced

The project brief asks for ERA+. That is the Baseball-Reference scale;
FanGraphs — the actual source — publishes **ERA-**. They are reciprocal:
ERA+ ≈ 10000 / ERA-. `era_minus` is stored (it is what the source gives) and
`era_plus` is generated. Pulling ERA+ separately from Baseball-Reference would
mean two run-environment models in one table, and columns that disagree.

### 3.4 `team_id` is a stable franchise code, not the display abbreviation

Cleveland became the Guardians in 2022; Oakland's identity changed in 2025. If
`team_id` were the display abbreviation, a rename would orphan years of stats
or require cascading rewrites. `team_id` is stable; `team_name` and
`fangraphs_abbrev` are attributes that can change.

**Known simplification:** `teams` holds *current* identity only, so a 2016 query
labels Cleveland "Guardians." No league or division realignment occurred within
2015–2025, so this is cosmetic. The fix, if it matters later, is a
`team_name_history(team_id, season_year, name)` relation — noted rather than
built, because it adds a join to every query for a label.

### 3.5 `seasons` carries `scheduled_games`

2020 was 60 games. Without this column, every per-162 rate, counting-stat
leaderboard and career-arc query treats 2020 as a collapse. One small lookup
relation makes the correction a join instead of a hardcoded `CASE WHEN
season_year = 2020`.

### 3.6 Two-way players need no special handling

Ohtani appears in both `batting_stats` and `pitching_stats`, each FK'd to the
same `players` row. This falls out of separating the fact tables by role rather
than by player — worth naming explicitly, because interviewers ask.

### 3.7 Oakland's abbreviation changed mid-window

The Athletics are `OAK` in the 2015–2024 data and `ATH` in 2025.
`teams.fangraphs_abbrev` holds one value per franchise, so the loader aliases
`ATH` to `OAK` rather than adding a second teams row. This is the concrete
payoff of §3.4: because `team_id` is a franchise code and not the display
abbreviation, a mid-window rename costs one line in the loader instead of a
schema change and a re-key.

### 3.8 `v_batting_season` excludes players who never batted

About 6,400 of the 15,521 batting rows have zero plate appearances — pitchers
who appear on the batting leaderboard without ever hitting. They are not
errors, so they stay in `batting_stats`, but they would distort every average,
rank and percentile in Phase 3, where 40% of the population would be empty
rows. `v_batting_season` filters `plate_appearances > 0`, leaving 9,173 real
batter-seasons. The table keeps the complete record; the view is the correct
default.

### 3.9 Switch-pitchers

`players.throws` accepts `'L'`, `'R'` and `'B'`, matching `bats`. Two players
in this window throw with both hands — Pat Venditte and Anthony Seigler — and
`'B'` is accurate data, not a load error. `throws` is NULL for the 1,417
position players who never pitched, since only the pitching feed carries it.

### 3.10 Primary position is single-valued; ambiguous players are NULL

FanGraphs reports every position a player appeared at, in scorebook order
rather than primary-first: `DH/OF`, `2B/3B/SS`, `C/1B`. `primary_position`
accepts one value, so the loader resolves them: DH, PH and PR are dropped when
a fielding position is also listed; an all-infield mix becomes `IF`; anything
still mixed (`2B/OF`) is NULL. The most recent season wins, and the batting
label beats the pitching one.

This leaves 1,362 players with an unambiguous position, 223 as `IF`, and 153
NULL. Position-based queries filter to the unambiguous set and say so —
a primary position is not well-defined for a genuine utility player, and
inventing one would be worse than excluding them.

### 3.11 `player_notes`: the one relation the app writes

Seven relations hold loaded data. The eighth holds scouting-style notes that
users write through the Flask app (the project's CRUD requirement).

- **Functional dependencies.** `note_id → player_id, category, body,
  created_at, updated_at`. `note_id` is the only candidate key and the only
  determinant, so the relation is in BCNF.
- **No `full_name` column.** Copying the name onto each note would add
  `player_id → full_name`, a dependency between non-key attributes (a 3NF
  violation) and an update anomaly the first time a name is corrected. The
  name is one join away.
- **`category` is a CHECK enum, not a lookup table.** Five fixed values
  (`hitting`, `pitching`, `defense`, `baserunning`, `general`) enforced by
  `CHECK (category IN (...))`. A `note_categories` table would make a new
  category a data change instead of a schema change, at the cost of a ninth
  relation and a join on every read. With five values that rarely change, the
  CHECK is simpler; the trade-off is that adding a category means editing
  `schema.sql` and the app's form.
- **The `body` CHECK trims tabs, CR and LF as well as spaces:**
  `length(trim(body, ' ' || char(9, 10, 13))) BETWEEN 1 AND 2000`. SQLite's
  one-argument `trim()` strips only spaces, so `'\n\n'` would have passed; the
  database backstop now matches the app's `strip()`.
- **`note_id` is `INTEGER PRIMARY KEY AUTOINCREMENT`,** so a deleted note's id
  is never handed out again. Note ids appear in URLs and in the orphans file,
  and must never come to point at a different note. The loader also carries
  the `sqlite_sequence` high-water mark across rebuilds.
- **Neither change affects normalization.** A CHECK and a key-generation rule
  add no attributes and no dependencies: the FDs above are unchanged and the
  relation stays in BCNF.
- **Same database file as `players`.** SQLite cannot enforce a foreign key
  across `ATTACH`ed databases, so a separate notes file would lose referential
  integrity. Keeping one file keeps the FK real.
- **`ON DELETE RESTRICT`, unlike the fact tables' `CASCADE`.** Stat rows can
  be re-downloaded; notes are the only data in the database that cannot. A
  player with notes cannot be deleted until the notes are dealt with.
- **The loader carries notes across rebuilds, and the rebuild is atomic.** The
  loader builds the complete new database in `<db>.tmp` and swaps it in with
  `os.replace` only after validation passes. It reads existing notes (read-only)
  before building, restores them with their original `note_id`, `created_at`
  and `updated_at` before validation (so `foreign_key_check` covers them),
  sets the new `sqlite_sequence` to the larger of its own and the old one, and
  writes any note whose player is no longer in the data to
  `database/player_notes_orphans.json` rather than dropping it. A failed load,
  a failed validation, or a locked file at swap time leaves the old database,
  notes included, byte-for-byte untouched. The earlier in-place rebuild could
  not promise that: `executescript` commits each `DROP` as it runs, so a
  failure partway through left a half-dropped database.
- **It is the only relation the app can write.** Page reads use a `mode=ro`
  connection. The notes POST handlers use a separate read-write connection
  with a `sqlite3` authorizer that denies by default and allows only reads,
  function calls, transactions, and `INSERT`/`UPDATE`/`DELETE` on
  `player_notes`. DDL, `ATTACH`, `PRAGMA` and writes to any other table are
  refused by SQLite itself, whatever SQL a handler sends.

---

## 4. Deliberate exceptions to strict normalization

Listing these is the point; an undocumented exception is a mistake, a
documented one is a decision.

1. **`is_multi_team` is redundant with `team_id IS NULL`.** The CHECK constraint
   `is_multi_team = 1 OR team_id IS NOT NULL` ties them together, so they cannot
   drift. Kept because SQL `NULL` is overloaded — a reader cannot tell "played
   for several clubs" from "we failed to load the team." The explicit flag also
   keeps Phase 3 queries readable. **Cost: one redundant boolean per row.**

2. **Imported metrics are snapshots.** FanGraphs recalculates WAR historically
   as its models change, so `war` is really "FanGraphs WAR as of the load date."
   The schema does not version this. The loader caches each pull in
   `database/raw/` and rebuilds from that cache, so a local database stays tied
   to one snapshot until `--refresh`. The cache is not in git (FanGraphs' terms
   prohibit redistribution), so two fresh clones built on different dates can
   hold different WAR values. A `loaded_at` column or a `data_loads` table would
   be the schema-level fix if loads ever need comparing directly.

3. **`payroll_usd` lives at the wrong native grain.** Payroll is
   contract-level data from a different source system, flattened to team-season.
   It is nullable and documented as externally sourced so a NULL reads as "not
   loaded," not "zero."

---

## 5. Source realities (resolved in Phase 2)

Each of these would have caused a wrong or empty load. How the loader handles them:

| Issue | Handling |
|---|---|
| **`pybaseball` is dead for FanGraphs.** It scrapes `leaders-legacy.aspx`, which FanGraphs retired and now answers with 403 | Call the JSON API backing the current site directly: `/api/leaders/major-league/data` |
| **Browser User-Agents get challenged.** A spoofed `Mozilla/5.0` hits a Cloudflare check | Send a descriptive UA naming the script. Identifying honestly is what works — and is the right thing regardless |
| **`qual` defaults to qualified batters only**, which would silently drop ~90% of the league | Pass `qual=0` and assert against the response's own `totalCount` |
| **Pagination truncates silently** if `pageitems` is too small | Assert `len(data) == totalCount`; a short read raises |
| **Multi-team players** appear as `2 Tms` … `5 Tms` | Map to `team_id = NULL, is_multi_team = 1` |
| **`playerTeamId` is the player's *current* club**, not the season's | Use `TeamNameAbb`. Ohtani's 2023 row is the test case: `teamid` 1 (LAA, correct) vs `playerTeamId` 22 (LAD) |
| **`Name` and `Team` are HTML anchors** | Use `PlayerName` and `TeamNameAbb` |
| **No `birth_date`** in the stat feed | Read the Chadwick register archive directly. `pybaseball.chadwick_register()` is not usable here — it keeps only names and ID keys and discards `birth_year`/`birth_month`/`birth_day` |
| **No payroll** in any FanGraphs feed | Manual CSV compiled from Spotrac and Cot's Contracts — 330 rows. Not in git; the loader leaves `payroll_usd` NULL without it |
| **IP arrives as `186.2`** (186⅔, not 186.2) | Convert to `outs_recorded` at load (§3.1) |
| **Zero-AB rows** report AVG/OBP/SLG as `0.0`; generated columns return NULL | Validation accepts NULL only where the source reports 0; NULL against any nonzero value still fails |
| **Oakland is `ATH` in 2025**, `OAK` before | Loader aliases it (§3.7) |
| **PowerShell adds a BOM** to any file it writes | Read every cached CSV with `encoding='utf-8-sig'` |
| **Raw payload is ~400 columns, ~12 MB/season** | Trim to mapped columns plus AVG/OBP/SLG/IP/ERA before caching — 6.5 MB for all 22 files |
| **Team stats** (W/L, RS/RA) aren't in the player feed | Separate pull with `team=0,ts`. W/L and runs allowed come from the pitching feed, runs scored from batting. `G` in both feeds sums player appearances — use pitching `GS` for team games |

### FanGraphs → schema column map (batting, abbreviated)

| JSON key | schema | JSON key | schema |
|---|---|---|---|
| `playerid` | `player_id` | `BB` | `walks` |
| `PlayerName` | `full_name` | `IBB` | `intentional_walks` |
| `TeamNameAbb` | `team_id` (`N Tms` → NULL) | `HBP` | `hit_by_pitch` |
| `Season` | `season_year` | `SO` | `strikeouts` |
| `G` | `games` | `SF` / `SH` | `sac_flies` / `sac_hits` |
| `PA` / `AB` | `plate_appearances` / `at_bats` | `SB` / `CS` | `stolen_bases` / `caught_stealing` |
| `H` / `2B` / `3B` / `HR` | `hits` / `doubles` / `triples` / `home_runs` | `wOBA` / `wRC+` / `WAR` | `woba` / `wrc_plus` / `war` |
| `R` / `RBI` | `runs` / `rbi` | `Offense` / `Defense` / `BaseRunning` | `off_runs` / `def_runs` / `bsr` |
| `Bats` / `Throws` / `position` | `players.bats` / `throws` / `primary_position` | | |

`AVG`, `OBP`, `SLG`, `OPS`, `ISO`, `BB%`, `K%` are **not loaded** — they are
generated. Use them as a validation check instead: recompute from the loaded
counting stats and compare to the FanGraphs values. A mismatch means a bad load.

---

## 6. Corrections to the original project brief

Carried forward so they don't resurface later:

- **`QUALIFY`** (brief, Query 1) is Snowflake/BigQuery syntax. SQLite has no
  `QUALIFY` — wrap the window function in a CTE and filter in the outer query.
- **`YEAR(birth_date)`** (brief, Query 10) is not a SQLite function. Use
  `CAST(strftime('%Y', birth_date) AS INTEGER)`.
- **f-string SQL in the Flask route** (brief, Phase 4 `search_player`) is a SQL
  injection hole — `name` goes straight from the query string into the
  statement. Use parameter binding (`?`) everywhere, including `LIKE`:
  `WHERE full_name LIKE ?` with `('%' + name + '%',)`. Worth doing right the
  first time and worth mentioning in interviews.
- **"6 core entities"** became 7 — `divisions` was split out to reach 3NF (§2).
  `player_notes` (§3.11) is an eighth, app-written relation, not a loaded entity.

---

## 7. Resolved decisions

All four questions Phase 1 left open were settled during the Phase 2 load:

1. **Payroll — loaded.** 330 team-seasons of Opening Day payroll, hand-built
   from Spotrac and Cot's Contracts. Keeps the payroll-efficiency and undervalued-player queries
   alive.
2. **Birth dates — loaded.** From the raw Chadwick register, matching all 4,019
   players. `mlbam_id` and `bbref_id` came along with them, so Statcast and
   Baseball-Reference joins are available later without a re-key.
3. **Position — from the API.** The leaderboard feed carries `position`, `Bats`
   and `Throws` directly, which the old stat pulls did not. Resolution rules and
   their limits are in §3.10.
4. **2025 — complete.** No partial-season flag needed in `seasons.note`.

Since resolved: `team_stats` now carries games, wins, losses, runs scored and
runs allowed for all 330 team-seasons, validated by two identities that must
hold exactly — league-wide wins equal losses, and runs scored equal runs
allowed, in every season. `playoff_result` remains NULL; it would need 330
hand-entered values and no planned query uses it.
---

## 8. Files

| File | Contents |
|---|---|
| `design/schema.sql` | `CREATE TABLE` / `CREATE VIEW` statements, constraints, indexes |
| `design/er-diagram.svg` | E-R diagram, crow's-foot notation |
| `design/schema-notes.md` | This document |
| `scripts/load_data.py` | Atomic loader: read existing notes → build `<db>.tmp` (schema → reference → batting → pitching → identity → payroll → team results → restore notes → validation) → swap in |
| `database/seed_reference.sql` | Divisions, teams and seasons (36 rows, hand-maintained) |
| `database/payroll.csv` | Opening Day payroll, 30 teams × 11 seasons. Gitignored, supplied locally (see `database/README.md`) |
| `database/raw/` | Trimmed API snapshots and the Chadwick extract. Gitignored, created by `load_data.py --refresh` |
| `database/baseball.db` | Generated — gitignored, rebuilt by the loader in seconds from `raw/` |

**Verification:** `python scripts/load_data.py` — rebuilds from `database/raw/`
(first run on a fresh clone: add `--refresh`) and exits non-zero on any
validation failure, leaving the existing database unchanged.
