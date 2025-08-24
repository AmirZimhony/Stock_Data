# Stock Data Scraper

A Python script that fetches stock data from the Finviz website and stores it in MongoDB. The script tracks stock price changes, rising/falling days, and accumulated changes over time.

## Purpose

This script:
- Scrapes stock data from Finviz screener pages
- Stores stock information in MongoDB with change tracking
- Calculates consecutive rising/falling days for each stock
- Tracks accumulated price changes over time
- Uses multi-threading for efficient data collection

## Prerequisites

- Python 3.7+
- MongoDB database (local or cloud)
- Virtual environment (recommended)

## Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Stock_Data
   ```

2. **Create and activate virtual environment**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables**
   Create a `.env` file in the project root:
   ```env
   MONGO_URI=mongodb+srv://username:password@cluster.mongodb.net/database?retryWrites=true&w=majority
   DB_NAME=stock_data
   COLLECTION_NAME=stocks
   ```

5. **Configure settings**
   Edit `config.json` to set:
   - `test_stocks`: Stocks to check for trading activity
   - `end_index`: Number of stocks to process
   - Environment-specific settings (dev/prod)

## Usage

### Basic Usage
```bash
# Run with development settings
python main.py --env dev

# Run with production settings  
python main.py --env prod
```

### What the script does:
1. Checks if trading is happening (using test stocks)
2. If trading detected, scrapes Finviz stock data
3. Updates MongoDB with new stock information
4. Calculates rising/falling day streaks
5. Tracks accumulated price changes

## Configuration

### Environment Settings (`config.json`)
```json
{
  "dev": {
    "test_stocks": ["AAPL", "MSFT"],
    "DB_name": "stock_test1", 
    "collection_name": "stocks_test",
    "end_index": 501
  },
  "prod": {
    "test_stocks": ["AAPL", "MSFT"],
    "DB_name": "stock_data",
    "collection_name": "stocks", 
    "end_index": 10501
  }
}
```

### Environment Variables (`.env`)
- `MONGO_URI`: MongoDB connection string
- `DB_NAME`: Database name (optional, uses config)
- `COLLECTION_NAME`: Collection name (optional, uses config)

## Data Structure

Each stock document contains:
- `serial_number`: Unique identifier
- `ticker`: Stock symbol
- `company`: Company name
- `sector`: Business sector
- `industry`: Industry classification
- `country`: Country of origin
- `market_cap`: Market capitalization
- `pe_ratio`: Price-to-earnings ratio
- `price`: Current stock price
- `change`: Daily price change percentage
- `volume`: Trading volume
- `numOfRisingDays`: Consecutive rising/falling days (positive/negative)
- `accumulatedChange`: Total accumulated change during streak

## Testing

Run the test suite:
```bash
pytest tests/
```

## File Structure

- `main.py`: Main script with configuration and orchestration
- `stock_functions.py`: Core data scraping and processing functions
- `config.json`: Environment-specific configuration
- `requirements.txt`: Python dependencies
- `tests/`: Test files
- `.env`: Environment variables (create this file)

## Troubleshooting

### Common Issues

1. **Module not found errors**
   - Make sure virtual environment is activated
   - Run `pip install -r requirements.txt`

2. **MongoDB connection errors**
   - Check your `.env` file has correct `MONGO_URI`
   - Verify database credentials and network access

3. **No trading detected**
   - Script checks if test stocks have trading activity
   - If markets are closed, script will skip data collection

4. **Proxy/Network errors**
   - Script uses proxy for Finviz requests
   - Check proxy settings in `stock_functions.py`

### Debug Mode
Add print statements or enable logging to see detailed execution:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## License

This project is for educational and research purposes.
