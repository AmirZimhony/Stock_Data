# Stock Data Scraper

A Python application that scrapes stock data from Finviz and stores it in MongoDB with trend analysis.


This script fetches stock data from the Finviz website and stores it in MongoDB.

Beginner's Instructions:
1. Download and install Python from https://www.python.org/downloads/
2. Install the required packages by running the following command in your terminal:
   `pip install -r requirements.txt`
3. Create a `.env` file in the project root with:
   - `db_url` — MongoDB connection string (required)
   - `nasdaq_scraping_url` — screener URL for page 1 (required)
   - `proxy_url` — HTTP(S) proxy URL, e.g. `http://user:pass@host:port` (required for scraping)
4. Run: `python main.py` loads `dev.json` when you omit `--env`. With `--env`, pass `--db-name`, `--collection-name`, `--max-workers`, `--end-index`.

## Features

- **Multi-threaded scraping** from Finviz screener
- **MongoDB storage** with trend tracking (rising days, accumulated change)
- **Container-optimized logging** (stdout + optional file logging)
- **Configurable screener URL and proxy** via `nasdaq_scraping_url` and `proxy_url` (required)
- **Error handling** with retry logic

## Quick Start

### Option 1: Docker (Recommended)

1. **Configure environment:** in `.env` next to `docker-compose.yml`, set `db_url`, `nasdaq_scraping_url`, and `proxy_url` (Compose passes them into the container). Or export those variables before `docker compose up`.

2. **Run with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

3. **View logs:**
   ```bash
   docker-compose logs -f
   ```

### Option 2: Local Python

1. **Create and activate virtual environment:**
   ```bash
   # Create virtual environment
   python3 -m venv venv
   
   # Activate virtual environment
   # On Windows:
   venv\Scripts\activate
   # On macOS/Linux:
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment:** add `db_url`, `nasdaq_scraping_url`, and `proxy_url` to `.env` (see Environment Variables below).

4. **Run the scraper:**
   ```bash
   python main.py
   ```

5. **Deactivate virtual environment when done:**
   ```bash
   deactivate
   ```

## Configuration

### Environment Variables

```bash
# Logging
LOG_LEVEL=INFO              # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_DIR=/app/logs           # Optional: directory for log files
CONTAINER_ENV=true          # Enable container-optimized logging

# Required for the app and for tests that hit the live screener
db_url=mongodb+srv://user:password@cluster.example.mongodb.net/?retryWrites=true&w=majority
nasdaq_scraping_url=example_scraping.com   # page 1; workers add &R=<start> for start>1
proxy_url=http://user:pass@proxy.example:80
```

`load_dotenv()` runs in `config.configure()` when you start `main.py`. Scraping reads `nasdaq_scraping_url` and `proxy_url` in `stock_functions.get_data` (both required; no defaults).

### Docker Configuration

The application includes Docker configuration for Linux AMD64:

- **Dockerfile**: Multi-stage build with Python 3.11 slim
- **docker-compose.yml**: Easy deployment with volume mounts
- **.dockerignore**: Optimized build context

**Docker commands:**
```bash
# Build image
docker build -t stock-scraper .

# Run container
docker run -d --name stock-scraper \
  -e db_url="your_mongodb_connection_string" \
  -e nasdaq_scraping_url="example-scraping.com" \
  -e proxy_url="http://user:pass@proxy:80" \
  -v $(pwd)/logs:/app/logs \
  stock-scraper

# Stop container
docker stop stock-scraper
```

### MongoDB Setup

Use `db_url` for Atlas. Omit `--env` to use `dev.json`. Use `--env <name>` plus the four flags for other targets.

## Project Structure

```
├── main.py                 # Entry point
├── dev.json                # Local dev DB/collection/workers (no --env)
├── config.py               # dev.json or CLI; Mongo URI from db_url env
├── stock_functions.py      # Core scraping and database functions
├── logging_config.py       # Simple logging configuration
├── Data_extracter.py       # Alternative scraper implementation
├── requirements.txt        # Python dependencies
└── tests/
    └── test_main.py        # Unit + live screener test; loads repo-root .env via dotenv
```

## Data Schema

Each stock record includes:
- Basic info: ticker, company, sector, industry, country
- Market data: price, change, volume, market cap, P/E ratio
- Trend analysis: `numOfRisingDays`, `accumulatedChange`

## Logging

The application uses container-optimized logging:
- **Stdout logging** (required for containers/Airflow)
- **Optional file logging** if `LOG_DIR` is writable
- **Log rotation** for file logs
- **Reduced noise** from third-party libraries

## Development

### Running Tests

```bash
python -m pytest tests/
```

`tests/test_main.py` calls `load_dotenv` on the repo-root `.env` at import time. `test_nasdaq_scraping_url_live_request` performs a real GET to `nasdaq_scraping_url` via `proxy_url` and asserts HTTP 200 and `screener_table` in the HTML; it raises if those env vars are missing. Network access required for that test.

## Build an image and push to Docker Hub
```bash
./docker-build.sh
```

### Logging Configuration
See [LOGGING_CONFIG.md](LOGGING_CONFIG.md) for detailed logging setup.

## Requirements

- Python 3.7+
- MongoDB Atlas account
- Internet connection for web scraping

## Dependencies

- `requests` - HTTP requests
- `beautifulsoup4` - HTML parsing
- `pymongo` - MongoDB operations
- `python-dotenv` - Load `.env` for `db_url`, `nasdaq_scraping_url`, `proxy_url`
- `pandas` - Data processing
- `numpy` - Numerical operations

## License

This project is for educational and research purposes.
