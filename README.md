# Stock Data Scraper

Fetches NASDAQ, NYSE, and NYSE American common-stock data from Yahoo Finance (yfinance) and stores it in MongoDB with trend analysis (rising days, accumulated change). No API key or proxy is needed.

## Modes

- `--mode daily` (default): batched Yahoo quote requests for price, change, volume, market cap, and P/E. Company, sector, industry, and country are written only when a ticker is first inserted (company from the quote, the others `-`).
- `--mode weekly`: one Yahoo `quoteSummary` request per stored ticker for company, sector, industry, and country. Tickers missing a sector go first. Missing values never overwrite stored ones. The first rate limit pauses 60 s; a second one stops the run, and the next weekly run continues.

Airflow runs daily mode in `nasdaq_stocks_<env>` and weekly mode in `nasdaq_profiles_<env>` (Saturdays), both against the same collection.

## Ticker universe

The Nasdaq Trader symbol directory (`nasdaqlisted.txt`, `otherlisted.txt`, free) lists every Nasdaq, NYSE, and NYSE American security. A listing is kept when:
- it is not an ETF and not a test issue;
- its security name does not mark a preferred share, unit, warrant, right, note or other debt, structured product, or ETN (partnership common units are kept);
- Yahoo reports its `quoteType` as `EQUITY`.

Ticker shape is not used, so `BRK-B` and `BF-B` stay. The run logs the count per exclusion category.

## Usage

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

`.env` in the project root needs only `db_url` (MongoDB connection string).

```bash
# dev.json (stock_test.stocks_test, first 100 tickers)
python main.py
python main.py --mode weekly

# staging (first 500 tickers)
python -u main.py --env staging --db-name stock_staging --collection-name nasdaq_stocks_staging --max-workers 5 --mode daily --limit 500

# production (all tickers)
python -u main.py --env prod --db-name stock_data --collection-name nasdaq_stocks --max-workers 30 --mode daily
python -u main.py --env prod --db-name stock_data --collection-name nasdaq_stocks --max-workers 30 --mode weekly
```

Flags:
- `--env NAME`: take settings from the flags below instead of `dev.json`.
- `--db-name`, `--collection-name`: MongoDB target.
- `--max-workers`: parallel MongoDB writers in daily mode.
- `--mode daily|weekly`: see Modes.
- `--limit N`: only the first N tickers of the sorted universe (staging checks).

A daily run fails (non-zero exit) when nothing was written or a quote batch failed after retries. Tickers with no Yahoo quote are logged and skipped. A weekly run fails only when no profile could be fetched.

## Data Schema

`change`, `volume`, `numOfRisingDays` and `accumulatedChange` are stored as native numbers (DP-103). The other fields keep the existing display strings. Documents written before the switch still hold strings (`"5.31%"`, `"88,958,281"`, `"3"`, `"4.25"`) until the ticker's next daily run rewrites `change` and `volume`, and its next run on a new trading day rewrites the streak fields. Tickers that are no longer quoted keep their strings. Every reader accepts both, and `stocks_standardizer` renders native numbers back to the same strings in `stocks_merged`.

| Field | Type | Example | Source |
|---|---|---|---|
| `serial_number` | int | `16` | row number in the run |
| `ticker` | str | `BRK-B` | symbol directory (`.` becomes `-`) |
| `company` | str | `Apple Inc` | `longName` / `shortName`, commas and trailing period removed |
| `sector` | str | `Financial` | `assetProfile.sector` (`Financial Services` -> `Financial`) |
| `industry` | str | `Consumer Electronics` | `assetProfile.industry` |
| `country` | str | `USA` | `assetProfile.country` (`United States` -> `USA`) |
| `market_cap` | str | `5100.81B`, `149.97M` | `marketCap` |
| `pe_ratio` | str | `38.94` | `trailingPE` |
| `price` | float or None | `349.51` | `regularMarketPrice` |
| `change` | float or None | `5.31`, `-1.2` | percent points (5.31 means 5.31%) of price vs `regularMarketPreviousClose`, 2 decimals |
| `volume` | int or None | `88958281` | `regularMarketVolume`, shares traded |
| `numOfRisingDays` | int | `3`, `-2` | computed by the writer |
| `accumulatedChange` | float | `4.25` | computed by the writer, percent points (a flat first-day insert stores the int `0`, matching the old text `"0"` in `stocks_merged`) |
| `timestamp` | datetime (UTC) | | last daily write |

Missing text fields are `-`. A missing `change`, `volume` or `price` is `None` (null); a real zero is stored as `0`. Documents are upserted by `ticker`.

## Project Structure

```
├── main.py               # Entry point: daily or weekly run, summary, metrics
├── config.py             # dev.json or CLI flags; Mongo URI from db_url
├── dev.json              # Local dev settings (no --env)
├── yfinance_scraper.py   # Universe, Yahoo quotes and profiles, document formatting
├── stock_functions.py    # MongoDB writer (rising days) and profile updates
├── legacy_finviz.py      # Former Finviz scraper, reference and rollback only
├── logging_config.py     # Logging configuration
└── tests/
    ├── test_yfinance_scraper.py           # Schema, formats, universe, failures, writes, CLI
    ├── test_legacy_finviz.py              # Legacy Finviz parser
    └── test_legacy_finviz_reliability.py  # Legacy Finviz pacing and retries
```

## Legacy Finviz scraper

`legacy_finviz.py` keeps the Finviz screener scraper unchanged. It is not on the active path. `legacy_finviz.run(collection, max_workers, end_index)` is the former `main.py` loop and needs `nasdaq_scraping_url` and `proxy_url`. The simplest rollback is to deploy the previous image tag.

## Docker

```bash
docker build -t stock-scraper .
docker run --rm -e db_url="your_mongodb_connection_string" stock-scraper \
  python -u main.py --env staging --db-name stock_staging --collection-name nasdaq_stocks_staging --max-workers 5 --mode daily --limit 500
```

The image build installs `stocker_metrics` from its public GitHub repo. No token is required.

## Logging

Logs go to stdout, plus a rotating file when `LOG_DIR` is writable. See [LOGGING_CONFIG.md](LOGGING_CONFIG.md).

## Development

```bash
python -m pytest tests/
ruff check . && ruff format --check .
```

All tests are mocked; none hit Yahoo or MongoDB.

## CI/CD

GitHub Actions (`.github/workflows/ci.yml`) runs on every push/PR to `main`:
- **lint**: `ruff check` / `ruff format --check`
- **test**: `pytest`
- **secret-scan**: `gitleaks`
- **docker-build**: on PRs only, pushes `amiroz/projects:stock_data_pr_<PR#>`
- **promote-latest**: on merge to `main`, retags that PR image to `amiroz/projects:stock_data_latest`

Repo secrets: `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`.

## Dependencies

- `yfinance` - Yahoo Finance client
- `pymongo` - MongoDB operations
- `python-dotenv` - loads `.env`
- `requests` - symbol directory downloads (and the legacy scraper)
- `beautifulsoup4` - legacy Finviz HTML parsing
- `pandas`, `numpy` - yfinance dependencies
- `pytest` - test runner
- `stocker_metrics` - run gauges over DogStatsD (`stocks.read`, `stocks.inserted`, `stocks.updated`; weekly `profiles.fetched`, `profiles.updated`)
