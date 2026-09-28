# Baseball Analytics Database

SQLite database of MLB season statistics, 2015–2025, with analytical SQL queries.

## Setup

```sh
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install pandas requests
python scripts/load_data.py --refresh
```

Source data is downloaded at setup, not stored in the repo. Payroll is optional and supplied locally. See [database/README.md](database/README.md) for details and data credits (FanGraphs; Chadwick Baseball Bureau, ODC-By 1.0; Spotrac and Cot's Contracts).

Queries: [queries/README.md](queries/README.md).
