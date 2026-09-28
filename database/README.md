# Database setup

`baseball.db` is not in the repo. `scripts/load_data.py` builds it from source data that is also not in the repo: the loader downloads it on first run, except for payroll, which you supply yourself.

## Build

From the repo root, with Python 3 (full walkthrough for Windows and macOS/Linux: [SETUP.md](../SETUP.md)):

```sh
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python scripts/load_data.py --refresh
```

`--refresh` downloads the FanGraphs season data (2015–2025) and the Chadwick register into `database/raw/`. Running the loader with `--refresh` fetches data from FanGraphs' API, and users are responsible for complying with FanGraphs' terms of service. After that, `python scripts/load_data.py` rebuilds from that local cache in seconds. If the cache is missing and `--refresh` is not given, the loader stops and tells you to run with `--refresh`.

The loader validates the build (recomputed rate stats against FanGraphs, league-wide W = L and RS = RA, foreign-key check) and exits non-zero on any mismatch.

## Payroll (optional)

Team payroll is read from `database/payroll.csv`. Without it, everything else loads, `team_stats.payroll_usd` stays NULL, and the loader prints a warning. The features that need payroll are Q03 (payroll efficiency), Q11 (cost per WAR) and the payroll charts.

Expected format: one header row, then one row per team per season (30 teams × 2015–2025 = 330 rows).

```csv
team_id,season_year,payroll_usd
ARI,2015,101219554
```

- `team_id`: the team codes in `database/seed_reference.sql`
- `season_year`: 2015–2025
- `payroll_usd`: Opening Day payroll in whole US dollars

To use a file elsewhere: `python scripts/load_data.py --payroll PATH`. An explicit `--payroll` path that doesn't exist is an error.

## Data sources and credits

- **FanGraphs** (fangraphs.com): player and team season statistics, fetched from the FanGraphs leaders API at setup. The data is not included in this repository because FanGraphs' terms of service prohibit redistributing their materials.
- **Chadwick Baseball Bureau Register** (github.com/chadwickbureau/register): player names, birth dates and cross-site IDs. Used under the Open Data Commons Attribution License (ODC-By 1.0). Downloaded at setup rather than stored in the repo.
- **Spotrac and Cot's Contracts**: Opening Day team payroll, compiled by hand from both sites. Not included because it is copied from third-party sites.
