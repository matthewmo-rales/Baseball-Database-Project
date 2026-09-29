# Setup

How to build the database, run the app and run the tests on a fresh clone. Every command is shown for Windows PowerShell and for macOS/Linux. Run everything from the repository root unless a step says otherwise.

## 1. Prerequisites

- **Python 3.14.** Tested on Python 3.14.7 with the bundled SQLite 3.50.4. The versions in `requirements.txt` are pinned to what was tested.
- **git.**
- An internet connection for the first database build.

Check your Python version (on Windows, if `py` isn't found, use `python` here and in step 2):

```powershell
# Windows PowerShell
py --version
```

```sh
# macOS/Linux
python3 --version
```

## 2. Clone and install

 The install step downloads about 30 packages; clone plus install took about three minutes in the check.

```powershell
# Windows PowerShell
git clone https://github.com/matthewmo-rales/Baseball-Database-Project Baseball-analytics-db
cd Baseball-analytics-db
py -3.14 -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

```sh
# macOS/Linux
git clone https://github.com/matthewmo-rales/Baseball-Database-Project Baseball-analytics-db
cd Baseball-analytics-db
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Every later step assumes the virtual environment is active (your prompt starts with `(venv)`). In a new terminal, activate it again with the activation line above. If PowerShell refuses to run `Activate.ps1`, see [Troubleshooting](#7-troubleshooting).

## 3. Build the database

```powershell
# Windows PowerShell
python scripts/load_data.py --refresh
```

```sh
# macOS/Linux
python scripts/load_data.py --refresh
```

`--refresh` downloads the source data into `database/raw/` and builds `database/baseball.db`:

- FanGraphs season statistics, 2015–2025: player batting, player pitching, team batting and team pitching, one request per season each (44 requests, one second apart), from FanGraphs' API. Running the loader with `--refresh` is your use of FanGraphs' API, and you are responsible for complying with FanGraphs' terms of service.
- The Chadwick Baseball Bureau player register (a ~30 MB zip from GitHub), for names, birth dates and IDs.

In the fresh-clone check for this guide, the build took about 2 minutes 40 seconds, almost all of it downloading, and `database/raw/` came to 45 files (about 6 MB). Your time depends on your connection.

The loader prints each step and ends with `OK: ...database/baseball.db`. Without a payroll file it also prints a payroll warning, which is expected (see step 4). It validates the build (rate stats recomputed and compared against FanGraphs, league-wide wins = losses and runs scored = runs allowed, foreign-key check) and exits with an error on any mismatch.

**Later rebuilds** don't need `--refresh`. `python scripts/load_data.py` rebuilds from the local `database/raw/` cache in a few seconds, without touching the network. Use `--refresh` again only when you want newer data from FanGraphs.

**Rebuilds are atomic and keep notes.** The new database is built in `database/baseball.db.tmp` and swapped in only after validation passes, so a failed rebuild leaves your existing database untouched. Player notes written in the app are carried over to the new database. A note whose player is no longer in the data is saved to `database/player_notes_orphans.json` instead of being dropped.

Data sources and credits: [database/README.md](database/README.md).

## 4. Optional: team payroll

Payroll is not in the repository (it is compiled by hand from third-party sites). Everything works without it except the payroll features:

- **Q03** (team payroll efficiency) and **Q11** (team cost per WAR) show a "Payroll data not loaded" panel instead of results.
- The payroll-vs-win% chart on the Charts page shows the same panel.
- Team pages show the same note and "—" in the payroll columns.

To load payroll, create `database/payroll.csv` with exactly these columns, one header row, and one row per team per season:

| Column | Contents |
| --- | --- |
| `team_id` | a team code from `database/seed_reference.sql` |
| `season_year` | 2015–2025 |
| `payroll_usd` | Opening Day payroll in whole US dollars |

Then rebuild (step 3, without `--refresh`). To read the file from somewhere else, pass `--payroll PATH`; a `--payroll` path that doesn't exist is an error. More detail: [database/README.md](database/README.md#payroll-optional).

## 5. Run the app

```powershell
# Windows PowerShell
flask --app app run
```

```sh
# macOS/Linux
flask --app app run
```

Open <http://127.0.0.1:5000>. Flask prints `WARNING: This is a development server`; that is expected for a local demo. Stop the server with Ctrl+C.

The app listens on 127.0.0.1 (this computer only). Don't add `--host 0.0.0.0`: this is a local demo, not a hardened deployment.

For local development, `flask --app app run --debug` adds auto-reload and the interactive debugger. Use `--debug` only on your own machine; the debugger can run code.

## 6. Run the tests

```powershell
# Windows PowerShell
pytest
```

```sh
# macOS/Linux
pytest
```

The suite (489 tests) takes about three minutes. The tests use a small fictional database built from `design/schema.sql`, so they don't need `database/baseball.db`. The 2 tests that check the real database are skipped when it hasn't been built (`487 passed, 2 skipped`).

## 7. Troubleshooting

**`LOAD FAILED at the final swap: ... is open in another program`**
Another program has `database/baseball.db` open, usually DB Browser for SQLite. This mostly happens on Windows. Close that program and run the loader again. Your existing database was not changed.

**The app shows "The database hasn't been built yet"**
`database/baseball.db` doesn't exist. Run step 3, then reload the page.

**Port 5000 is already in use** (`Address already in use`)
Another program is using port 5000. On macOS this is often AirPlay Receiver. Run on another port and open that port instead:

```powershell
# Windows PowerShell
flask --app app run --port 5001
```

```sh
# macOS/Linux
flask --app app run --port 5001
```

**PowerShell: `Activate.ps1 cannot be loaded because running scripts is disabled`**
Allow scripts for the current PowerShell window only, then activate again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
venv\Scripts\Activate.ps1
```
