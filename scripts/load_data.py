"""
Phase 2 loader: build database/baseball.db from scratch.

Steps, in order:
  1. design/schema.sql            -- drops and recreates every table/view
  2. database/seed_reference.sql  -- divisions, teams, seasons
  3. FanGraphs batting + pitching season aggregates, 2015-2025, from the
     FanGraphs leaders JSON API (plus bats/throws/position for players)
  4. Player identity from the Chadwick register (names, IDs, birth date, debut)
  5. Team payroll from a CSV (team_id, season_year, payroll_usd). Optional:
     without the file, payroll_usd stays NULL and everything else loads.
  6. Team results (G, W, L, RS, RA) from the same API's team totals (team=0,ts)
  7. Validation: recompute AVG/OBP/SLG/ERA/IP from loaded counting stats and
     compare against the FanGraphs values; check league-wide W = L and RS = RA.
     Any mismatch = bad load, exit 1.

Every raw pull is cached as CSV under database/raw/ and reused on later runs,
so a reload is reproducible against the same local snapshot (FanGraphs revises
WAR historically -- see schema-notes.md section 4.2). The FanGraphs cache is
not in git (their terms prohibit redistribution), so the first run on a fresh
clone must use --refresh. Without --refresh, missing cache files are an error.

Usage:
    python scripts/load_data.py [--refresh] [--payroll PATH]
"""

import argparse
import io
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import requests

REPO = Path(__file__).resolve().parent.parent
SCHEMA_SQL = REPO / "design" / "schema.sql"
SEED_SQL = REPO / "database" / "seed_reference.sql"
DEFAULT_DB = REPO / "database" / "baseball.db"
DEFAULT_CACHE = REPO / "database" / "raw"
DEFAULT_PAYROLL = REPO / "database" / "payroll.csv"

SEASONS = range(2015, 2026)

# A qual=0 pull returns ~1,300-1,500 batters and ~800-900 pitchers per season
# (fewer in 2020). A qualified-only pull returns ~140 / ~60. These floors sit
# well between the two so a silently-applied qual filter fails loudly.
MIN_ROWS = {"batting": 500, "pitching": 400}

# pybaseball scrapes leaders-legacy.aspx, which FanGraphs now blocks. The JSON
# API behind the current leaderboard serves the same data. Identify the script
# honestly -- a spoofed browser UA is what gets the Cloudflare challenge.
FANGRAPHS_API = "https://www.fangraphs.com/api/leaders/major-league/data"
USER_AGENT = "baseball-analytics-db/1.0 (CSC 4402 course project; scripts/load_data.py; python-requests)"
PAGE_ITEMS = 10000          # one page holds a full season (~1,500 batters)
REQUEST_DELAY = 1.0         # seconds between live pulls

# FanGraphs has used "- - -" for multi-team players; the JSON API uses "2 Tms".
MULTI_TEAM = re.compile(r"^(- - -|\d+\s*Tms)$")

# teams.fangraphs_abbrev holds one value per franchise, but FanGraphs switched
# the Athletics from OAK (2015-2024) to ATH (2025). Older labels stay in the
# seed; newer ones are aliased here.
TEAM_ALIASES = {"ATH": "OAK"}

# Positions allowed by the players.primary_position CHECK in schema.sql.
POSITIONS = {"C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "DH", "SP", "RP", "P", "OF", "IF"}
INFIELD = {"1B", "2B", "3B", "SS"}
# Not fielding positions. PH/PR (pinch hitter/runner) appear in the payload
# but are not valid primary positions.
NON_FIELDING = {"DH", "PH", "PR"}

# pybaseball's chadwick_register() fetches this same archive but keeps only
# names and ID keys -- it drops birth_year/month/day. Read the people files
# directly so one download covers identity and birth date.
CHADWICK_URL = "https://github.com/chadwickbureau/register/archive/refs/heads/master.zip"
CHADWICK_COLS = [
    "key_fangraphs", "key_mlbam", "key_bbref", "name_first", "name_last",
    "birth_year", "birth_month", "birth_day", "mlb_played_first",
]

# FanGraphs JSON key -> schema column, with the Python type to coerce to.
# Rate stats (AVG, OBP, ERA, K/9, ...) are deliberately absent: they are
# generated columns in schema.sql and are used only for validation below.
# The payload's `Name`/`Team` are HTML links and `playerTeamId` is the
# player's CURRENT club, not the season's -- none of them are read.
BATTING_MAP = {
    "G": ("games", int), "PA": ("plate_appearances", int), "AB": ("at_bats", int),
    "H": ("hits", int), "2B": ("doubles", int), "3B": ("triples", int),
    "HR": ("home_runs", int), "R": ("runs", int), "RBI": ("rbi", int),
    "BB": ("walks", int), "IBB": ("intentional_walks", int),
    "HBP": ("hit_by_pitch", int), "SO": ("strikeouts", int),
    "SF": ("sac_flies", int), "SH": ("sac_hits", int),
    "SB": ("stolen_bases", int), "CS": ("caught_stealing", int),
    "wOBA": ("woba", float), "wRC+": ("wrc_plus", int), "WAR": ("war", float),
    "Offense": ("off_runs", float), "Defense": ("def_runs", float),
    "BaseRunning": ("bsr", float),
}

PITCHING_MAP = {
    "G": ("games", int), "GS": ("games_started", int), "W": ("wins", int),
    "L": ("losses", int), "SV": ("saves", int), "TBF": ("batters_faced", int),
    "H": ("hits_allowed", int), "R": ("runs_allowed", int),
    "ER": ("earned_runs", int), "HR": ("home_runs_allowed", int),
    "BB": ("walks", int), "IBB": ("intentional_walks", int),
    "HBP": ("hit_batters", int), "SO": ("strikeouts", int),
    "FIP": ("fip", float), "xFIP": ("xfip", float), "ERA-": ("era_minus", float),
    "FIP-": ("fip_minus", float), "WAR": ("war", float),
    "LOB%": ("lob_pct", float), "BABIP": ("babip_against", float),
}

# Columns written to the database/raw/ cache: identity, the stat map, and the
# FanGraphs rate stats that validate() compares against. The raw payload has
# 500+ columns per player; everything else is dropped before caching.
IDENTITY_COLS = ["playerid", "PlayerName", "TeamNameAbb", "Season", "position"]
CACHE_COLS = {
    "batting": [*IDENTITY_COLS, "Bats", *BATTING_MAP, "AVG", "OBP", "SLG"],
    "pitching": [*IDENTITY_COLS, "Throws", "IP", *PITCHING_MAP, "ERA"],
}

# Team totals (team=0,ts): one row per club. W/L exist only in the pitching
# feed (summed pitcher decisions = team record). Both feeds' `G` is a sum of
# player appearances, not team games; pitching GS is the team's game count.
TEAM_MAP = {
    "batting": {"R": ("runs_scored", int)},
    "pitching": {"GS": ("games_played", int), "W": ("wins", int),
                 "L": ("losses", int), "R": ("runs_allowed", int)},
}
TEAM_CACHE_COLS = {kind: ["TeamNameAbb", "Season", *cols] for kind, cols in TEAM_MAP.items()}
TEAMS_PER_SEASON = 30

PLAYER_SQL = {
    # Seasons load oldest-first, so the latest non-null value wins.
    "batting": """
        INSERT INTO players (player_id, full_name, bats, primary_position) VALUES (?, ?, ?, ?)
        ON CONFLICT (player_id) DO UPDATE SET
            full_name        = excluded.full_name,
            bats             = COALESCE(excluded.bats, players.bats),
            primary_position = COALESCE(excluded.primary_position, players.primary_position)""",
    # Batting's position wins over pitching's: pitchers already read 'P' there,
    # and it keeps a two-way player's batting role instead of overwriting it.
    "pitching": """
        INSERT INTO players (player_id, full_name, throws, primary_position) VALUES (?, ?, ?, ?)
        ON CONFLICT (player_id) DO UPDATE SET
            full_name        = excluded.full_name,
            throws           = COALESCE(excluded.throws, players.throws),
            primary_position = COALESCE(players.primary_position, excluded.primary_position)""",
}


class LoadError(Exception):
    pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    conn.executescript(path.read_text(encoding="utf-8"))
    # executescript runs statements verbatim; re-assert in case a script
    # ever turns enforcement off.
    conn.execute("PRAGMA foreign_keys = ON")


def coerce(value, kind):
    """pandas/numpy scalar -> plain Python int/float/None (sqlite3 can't bind numpy types)."""
    if value is None or pd.isna(value):
        return None
    return int(round(float(value))) if kind is int else float(value)


def text(value):
    """Blank/NaN -> None, else stripped string."""
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    return str(value).strip()


def primary_position(raw, label: str):
    """
    FanGraphs season position -> a value allowed by players.primary_position.

    Multi-position seasons arrive as 'DH/OF', '2B/3B/SS', 'C/1B' -- listed in
    scorebook order, not primary-first -- so they are reduced conservatively:
    DH/PH/PR are dropped when a fielding position is present, an all-infield
    mix becomes 'IF', and anything still ambiguous (e.g. '2B/OF') is NULL.
    """
    raw = text(raw)
    if raw is None:
        return None
    parts = raw.split("/")
    unknown = [p for p in parts if p not in POSITIONS | NON_FIELDING]
    if unknown:
        raise LoadError(f"{label}: unrecognized position {raw!r}")
    fielding = [p for p in parts if p not in NON_FIELDING]
    if not fielding:
        return "DH" if "DH" in parts else None    # 'PH/PR' -> NULL
    parts = fielding
    if len(parts) == 1:
        return parts[0]
    if set(parts) <= INFIELD:
        return "IF"
    return None


def ip_to_outs(ip) -> int:
    """FanGraphs IP display notation (180.1 = 180 1/3) -> outs recorded."""
    whole = int(ip)
    thirds = round((ip % 1) * 10)
    if thirds not in (0, 1, 2):
        raise LoadError(f"IP value {ip!r} is not valid baseball notation")
    return whole * 3 + thirds


def upsert_sql(table: str, columns: list[str], conflict: str) -> str:
    placeholders = ", ".join("?" for _ in columns)
    keys = {c.strip() for c in conflict.split(",")}
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in keys)
    return (f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}")


# ---------------------------------------------------------------------------
# FanGraphs pulls
# ---------------------------------------------------------------------------
def pull_fangraphs(kind: str, year: int, teams: bool = False) -> pd.DataFrame:
    """
    One season from the FanGraphs leaders JSON API, trimmed to CACHE_COLS.
    teams=True asks for team totals (team=0,ts) instead of per-player rows.
    """
    params = {
        "pos": "all", "stats": "bat" if kind == "batting" else "pit", "lg": "all",
        "qual": 0, "season": year, "season1": year, "month": 0,
        "team": "0,ts" if teams else 0,
        "ind": 1, "rost": 0, "type": 8, "pageitems": PAGE_ITEMS, "pagenum": 1,
    }
    if teams:
        kind, cols = f"team {kind}", TEAM_CACHE_COLS[kind]
    else:
        cols = CACHE_COLS[kind]
    print(f"  pulling {kind} {year} from FanGraphs ...")
    try:
        resp = requests.get(FANGRAPHS_API, params=params,
                            headers={"User-Agent": USER_AGENT}, timeout=120)
        resp.raise_for_status()
        payload = resp.json()   # a Cloudflare challenge page fails here, not later
    except (requests.RequestException, ValueError) as exc:
        raise LoadError(f"FanGraphs pull failed for {kind} {year}: {exc}") from exc
    time.sleep(REQUEST_DELAY)

    rows, total = payload["data"], payload["totalCount"]
    if len(rows) != total:
        raise LoadError(f"{kind} {year}: got {len(rows)} of totalCount={total} rows "
                        f"-- pagination is truncating (raise PAGE_ITEMS)")
    df = pd.DataFrame(rows)
    require_columns(df, cols, f"{kind} {year}")
    return df[cols]


def fetch_season(kind: str, year: int, cache_dir: Path, refresh: bool) -> pd.DataFrame:
    cache_file = cache_dir / f"{kind}_{year}.csv"
    if cache_file.exists() and not refresh:
        # utf-8-sig: a CSV that passed through PowerShell may have gained a BOM.
        df = pd.read_csv(cache_file, encoding="utf-8-sig")
        require_columns(df, CACHE_COLS[kind], cache_file.name)
    else:
        df = pull_fangraphs(kind, year)
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_file, index=False, encoding="utf-8")

    if not (df["Season"] == year).all():
        raise LoadError(f"{cache_file.name}: contains seasons other than {year} (was ind=1 used?)")
    dupes = df["playerid"][df["playerid"].duplicated()]
    if len(dupes):
        raise LoadError(f"{kind} {year}: player IDs appear more than once {dupes.head().tolist()} "
                        f"-- grain is one row per player per season")
    if len(df) < MIN_ROWS[kind]:
        raise LoadError(
            f"{kind} {year}: only {len(df)} rows. Expected well over {MIN_ROWS[kind]} "
            f"-- the qualified-players filter is probably on (need qual=0)."
        )
    return df


def fetch_team_season(kind: str, year: int, cache_dir: Path, refresh: bool) -> pd.DataFrame:
    cache_file = cache_dir / f"team_{kind}_{year}.csv"
    if cache_file.exists() and not refresh:
        df = pd.read_csv(cache_file, encoding="utf-8-sig")
        require_columns(df, TEAM_CACHE_COLS[kind], cache_file.name)
    else:
        df = pull_fangraphs(kind, year, teams=True)
        cache_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(cache_file, index=False, encoding="utf-8")

    if not (df["Season"] == year).all():
        raise LoadError(f"{cache_file.name}: contains seasons other than {year} (was ind=1 used?)")
    if len(df) != TEAMS_PER_SEASON:
        raise LoadError(f"team {kind} {year}: {len(df)} rows, expected {TEAMS_PER_SEASON} "
                        f"-- was team=0,ts used?")
    return df


def require_columns(df: pd.DataFrame, cols, label: str) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise LoadError(f"{label}: missing expected FanGraphs columns {missing}")


def resolve_team(raw, team_map: dict, label: str) -> tuple:
    """-> (team_id, is_multi_team). Unknown abbreviations fail instead of becoming NULL."""
    raw = str(raw).strip()
    if MULTI_TEAM.match(raw):
        return None, 1
    raw = TEAM_ALIASES.get(raw, raw)
    if raw not in team_map:
        raise LoadError(
            f"{label}: team abbreviation {raw!r} has no match in teams.fangraphs_abbrev. "
            f"Fix database/seed_reference.sql."
        )
    return team_map[raw], 0


def load_stats(conn, kind, cache_dir, refresh) -> pd.DataFrame:
    """Load one fact table for every season. Returns the raw frames for validation."""
    stat_map = BATTING_MAP if kind == "batting" else PITCHING_MAP
    table = f"{kind}_stats"
    team_map = dict(conn.execute("SELECT fangraphs_abbrev, team_id FROM teams"))

    columns = ["player_id", "season_year", "team_id", "is_multi_team"]
    if kind == "pitching":
        columns.append("outs_recorded")
    columns += [col for col, _ in stat_map.values()]
    stat_sql = upsert_sql(table, columns, "player_id, season_year")
    hand_col = "Bats" if kind == "batting" else "Throws"

    frames = []
    for year in SEASONS:
        df = fetch_season(kind, year, cache_dir, refresh)
        label = f"{kind} {year}"

        players, rows = [], []
        for rec in df.to_dict("records"):
            player_id = coerce(rec["playerid"], int)
            # TeamNameAbb is the season's club; playerTeamId (not cached) is the current one.
            team_id, multi = resolve_team(rec["TeamNameAbb"], team_map, label)
            row = [player_id, year, team_id, multi]
            if kind == "pitching":
                row.append(ip_to_outs(rec["IP"]))
            row += [coerce(rec[src], typ) for src, (_, typ) in stat_map.items()]
            players.append((player_id, text(rec["PlayerName"]), text(rec[hand_col]),
                            primary_position(rec["position"], label)))
            rows.append(row)

        with conn:
            conn.executemany(PLAYER_SQL[kind], players)
            conn.executemany(stat_sql, rows)
        print(f"  {label}: {len(rows):,} rows")
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Chadwick register
# ---------------------------------------------------------------------------
def fetch_chadwick(cache_dir: Path, refresh: bool) -> pd.DataFrame:
    cache_file = cache_dir / "chadwick_register.csv"
    if cache_file.exists() and not refresh:
        return pd.read_csv(cache_file, encoding="utf-8-sig")

    print("  downloading Chadwick register (~30 MB) ...")
    resp = requests.get(CHADWICK_URL, timeout=300)
    resp.raise_for_status()
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    people = [n for n in archive.namelist() if re.search(r"/people-[0-9a-f]+\.csv$", n)]
    if not people:
        raise LoadError("Chadwick archive contains no people-*.csv files; layout changed?")
    df = pd.concat(
        (pd.read_csv(archive.open(n), usecols=CHADWICK_COLS, low_memory=False) for n in people),
        ignore_index=True,
    )
    df = df[df["key_fangraphs"].notna()]
    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_file, index=False, encoding="utf-8")
    return df


def birth_date(rec):
    parts = [coerce(rec[c], int) for c in ("birth_year", "birth_month", "birth_day")]
    if None in parts:
        return None
    return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"


def load_chadwick(conn, cache_dir, refresh) -> None:
    reg = fetch_chadwick(cache_dir, refresh)
    loaded = {pid for (pid,) in conn.execute("SELECT player_id FROM players")}
    reg = reg[reg["key_fangraphs"].astype(int).isin(loaded)]
    if reg["key_fangraphs"].duplicated().any():
        raise LoadError("Chadwick register maps one FanGraphs ID to multiple people")

    updates = [
        (rec["name_first"] if pd.notna(rec["name_first"]) else None,
         rec["name_last"] if pd.notna(rec["name_last"]) else None,
         birth_date(rec),
         coerce(rec["mlb_played_first"], int),
         coerce(rec["key_mlbam"], int),
         rec["key_bbref"] if pd.notna(rec["key_bbref"]) else None,
         coerce(rec["key_fangraphs"], int))
        for rec in reg.to_dict("records")
    ]
    with conn:
        conn.executemany(
            """UPDATE players
                  SET first_name = ?, last_name = ?, birth_date = ?,
                      debut_year = ?, mlbam_id = ?, bbref_id = ?
                WHERE player_id = ?""",
            updates,
        )
    print(f"  matched {len(updates):,} of {len(loaded):,} players "
          f"({len(loaded) - len(updates):,} not in register)")


# ---------------------------------------------------------------------------
# payroll
# ---------------------------------------------------------------------------
def load_payroll(conn, path: Path, required: bool) -> bool:
    """Returns False (payroll_usd left NULL) when the default file is absent."""
    if not path.exists():
        if required:
            raise LoadError(f"payroll file not found: {path}")
        print(f"  WARNING: {path} not found; payroll_usd left NULL.\n"
              f"  Features that need it: Q03 (payroll efficiency), Q11 (cost per WAR), payroll charts.\n"
              f"  See database/README.md for the expected CSV format.")
        return False
    df = pd.read_csv(path, encoding="utf-8-sig")
    require_columns(df, ["team_id", "season_year", "payroll_usd"], path.name)
    if df.duplicated(["team_id", "season_year"]).any():
        raise LoadError(f"{path.name}: duplicate (team_id, season_year) rows")

    rows = [(str(r["team_id"]).strip(), coerce(r["season_year"], int), coerce(r["payroll_usd"], int))
            for r in df.to_dict("records")]
    # Only payroll is set here; load_team_results() fills G/W/L/RS/RA on the
    # same rows without touching payroll_usd.
    with conn:
        conn.executemany(
            upsert_sql("team_stats", ["team_id", "season_year", "payroll_usd"], "team_id, season_year"),
            rows,
        )
    print(f"  {len(rows):,} team-season payroll rows")
    return True


# ---------------------------------------------------------------------------
# team results
# ---------------------------------------------------------------------------
def load_team_results(conn, cache_dir, refresh) -> None:
    team_map = dict(conn.execute("SELECT fangraphs_abbrev, team_id FROM teams"))
    columns = ["team_id", "season_year"] + [col for m in TEAM_MAP.values() for col, _ in m.values()]
    # upsert_sql only SETs the listed columns, so payroll_usd from step 6 survives.
    sql = upsert_sql("team_stats", columns, "team_id, season_year")

    total = 0
    for year in SEASONS:
        merged = None
        for kind, stat_map in TEAM_MAP.items():
            df = fetch_team_season(kind, year, cache_dir, refresh)
            label = f"team {kind} {year}"
            recs = {}
            for rec in df.to_dict("records"):
                team_id, multi = resolve_team(rec["TeamNameAbb"], team_map, label)
                if multi:
                    raise LoadError(f"{label}: multi-team label {rec['TeamNameAbb']!r} in team totals")
                if team_id in recs:
                    raise LoadError(f"{label}: {team_id} appears more than once")
                recs[team_id] = [coerce(rec[src], typ) for src, (_, typ) in stat_map.items()]
            if merged is None:
                merged = recs
            elif recs.keys() != merged.keys():
                raise LoadError(f"team {year}: batting and pitching feeds list different teams")
            else:
                merged = {t: merged[t] + recs[t] for t in merged}

        with conn:
            conn.executemany(sql, [[team_id, year, *vals] for team_id, vals in merged.items()])
        total += len(merged)
    print(f"  {total:,} team-season result rows")


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def compare(label, merged, pairs, tol) -> int:
    bad = 0
    for db_col, fg_col in pairs:
        m = merged[merged[fg_col].notna() & merged[db_col].notna()]
        diff = m[(m[db_col] - m[fg_col]).abs() > tol]
        # The generated columns return NULL when the denominator is 0 (e.g. a
        # pitcher with 0 AB); FanGraphs reports 0 for the same undefined rate.
        # A NULL against any nonzero FanGraphs value is still a mismatch.
        null_mismatch = merged[merged[fg_col].notna() & (merged[fg_col] != 0) & merged[db_col].isna()]
        for name, rows in (("value", diff), ("missing", null_mismatch)):
            if len(rows):
                bad += len(rows)
                print(f"  MISMATCH {label} {db_col} vs FanGraphs {fg_col} ({name}): {len(rows)} rows")
                print(rows[["player_id", "season_year", db_col, fg_col]].head(5).to_string(index=False))
    return bad


def validate(conn, batting_raw, pitching_raw) -> int:
    bat = pd.read_sql("SELECT player_id, season_year, batting_avg, obp, slg FROM batting_stats", conn)
    fg = batting_raw.rename(columns={"playerid": "player_id", "Season": "season_year"})
    bat = bat.merge(fg[["player_id", "season_year", "AVG", "OBP", "SLG"]], on=["player_id", "season_year"])
    # DB rounds to 3 places; FanGraphs ships more precision. 0.0006 allows rounding only.
    bad = compare("batting", bat, [("batting_avg", "AVG"), ("obp", "OBP"), ("slg", "SLG")], 0.0006)

    pit = pd.read_sql("SELECT player_id, season_year, ip_display, era, outs_recorded FROM pitching_stats", conn)
    fg = pitching_raw.rename(columns={"playerid": "player_id", "Season": "season_year"})
    pit = pit.merge(fg[["player_id", "season_year", "IP", "ERA"]], on=["player_id", "season_year"])
    bad += compare("pitching", pit, [("ip_display", "IP")], 0.001)
    bad += compare("pitching", pit[pit["outs_recorded"] > 0], [("era", "ERA")], 0.006)

    # Every game has one winner and one loser, and every run scored is a run
    # allowed, so league-wide totals must balance exactly within each season.
    for year, w, l, rs, ra in conn.execute(
            """SELECT season_year, SUM(wins), SUM(losses), SUM(runs_scored), SUM(runs_allowed)
                 FROM team_stats GROUP BY season_year ORDER BY season_year"""):
        if w != l or rs != ra:
            print(f"  MISMATCH team_stats {year}: W={w} L={l} RS={rs} RA={ra}")
            bad += 1
    missing = conn.execute("SELECT COUNT(*) FROM team_stats WHERE wins IS NULL").fetchone()[0]
    if missing:
        print(f"  MISSING team_stats results: {missing} rows with NULL wins")
        bad += missing

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("players", "batting_stats", "pitching_stats", "team_stats")}
    print("  " + ", ".join(f"{t}={n:,}" for t, n in counts.items()))
    fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        print(f"  FOREIGN KEY violations: {fk[:5]}")
        bad += len(fk)
    return bad


# ---------------------------------------------------------------------------
def missing_fangraphs_cache(cache_dir: Path) -> list[str]:
    names = [f"{prefix}{kind}_{year}.csv"
             for prefix in ("", "team_") for kind in ("batting", "pitching") for year in SEASONS]
    return [n for n in names if not (cache_dir / n).exists()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-pull sources instead of using database/raw/ cache")
    ap.add_argument("--payroll", type=Path, default=None,
                    help=f"payroll CSV (default: {DEFAULT_PAYROLL}, skipped with a warning if absent)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="output database (default: %(default)s)")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE, help="raw pull cache (default: %(default)s)")
    args = ap.parse_args()

    # Check before connect(): the schema step drops every table, so failing
    # here leaves an existing database untouched.
    if not args.refresh:
        missing = missing_fangraphs_cache(args.cache_dir)
        if missing:
            print(f"LOAD FAILED: {len(missing)} FanGraphs cache files missing from {args.cache_dir} "
                  f"(e.g. {missing[0]}).\n"
                  f"They are not in git. Run:  python scripts/load_data.py --refresh",
                  file=sys.stderr)
            return 1

    conn = connect(args.db)
    try:
        print("[1/8] schema");     run_sql_file(conn, SCHEMA_SQL)
        print("[2/8] reference");  run_sql_file(conn, SEED_SQL)
        print("[3/8] batting");    batting = load_stats(conn, "batting", args.cache_dir, args.refresh)
        print("[4/8] pitching");   pitching = load_stats(conn, "pitching", args.cache_dir, args.refresh)
        print("[5/8] identity");   load_chadwick(conn, args.cache_dir, args.refresh)
        print("[6/8] payroll");    has_payroll = load_payroll(conn, args.payroll or DEFAULT_PAYROLL,
                                                              required=args.payroll is not None)
        print("[7/8] team results"); load_team_results(conn, args.cache_dir, args.refresh)
        print("[8/8] validation"); bad = validate(conn, batting, pitching)
    except LoadError as exc:
        print(f"\nLOAD FAILED: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    if bad:
        print(f"\nVALIDATION FAILED: {bad} mismatched values -- treat this load as bad.", file=sys.stderr)
        return 1
    print(f"\nOK: {args.db}" + ("" if has_payroll else " (without payroll: Q03, Q11 and payroll charts need it)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
