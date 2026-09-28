# Baseball Analytics Database

SQLite database of MLB season statistics, 2015–2025, with analytical SQL queries.

## Quick start

```sh
py -3.14 -m venv venv; venv\Scripts\Activate.ps1   # macOS/Linux: python3 -m venv venv; source venv/bin/activate
pip install -r requirements.txt
python scripts/load_data.py --refresh
flask --app app run                                # then open http://127.0.0.1:5000
```

Step-by-step instructions for Windows and macOS/Linux, optional payroll, tests and troubleshooting: [SETUP.md](SETUP.md).

Source data is downloaded at setup, not stored in the repo. Payroll is optional and supplied locally. See [database/README.md](database/README.md) for details and data credits (FanGraphs; Chadwick Baseball Bureau, ODC-By 1.0; Spotrac and Cot's Contracts).

Queries: [queries/README.md](queries/README.md).
