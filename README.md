# Stock Data Scraper

A Python application that scrapes stock data from Finviz and stores it in MongoDB with trend analysis.


This script fetches stock data from the Finviz website and stores it in MongoDB.

Beginner's Instructions:
1. Download and install Python from https://www.python.org/downloads/
2. Install the required packages by running the following command in your terminal:
   `pip install -r requirements.txt`
3. Replace the `CONNECTION_URI`, `DB_NAME`, and `COLLECTION_NAME` constants with your MongoDB connection details.
4. Run the script using the following command:
   `python main.py`    
"""

## Features

- **Multi-threaded scraping** from Finviz screener
- **MongoDB storage** with trend tracking (rising days, accumulated change)
- **Container-optimized logging** (stdout + optional file logging)
- **Proxy support** for reliable data fetching
- **Error handling** with retry logic

## Quick Start

### Option 1: Docker (Recommended)

1. **Configure MongoDB:**
   - Create `secret.json` with your MongoDB credentials:
   ```json
   {
     "db_username": "your_username",
     "db_password": "your_password"
   }
   ```

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

3. **Configure MongoDB:**
   - Create `secret.json` with your MongoDB credentials:
   ```json
   {
     "db_username": "your_username",
     "db_password": "your_password"
   }
   ```

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

# MongoDB (or use secret.json)
DB_USERNAME=your_username
DB_PASSWORD=your_password
```

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
  -v $(pwd)/secret.json:/app/secret.json:ro \
  -v $(pwd)/logs:/app/logs \
  stock-scraper

# Stop container
docker stop stock-scraper
```

### MongoDB Setup

The application connects to MongoDB Atlas using the credentials in `/secret.json`:
- Database: `stock_data`
- Collection: `stocks`

## Project Structure

```
├── main.py                 # Main scraper with multi-threading
├── stock_functions.py      # Core scraping and database functions
├── logging_config.py       # Simple logging configuration
├── Data_extracter.py       # Alternative scraper implementation
├── requirements.txt        # Python dependencies
└── tests/                  # Test files
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
- `pandas` - Data processing
- `numpy` - Numerical operations

## License

This project is for educational and research purposes.
