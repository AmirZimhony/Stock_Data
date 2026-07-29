# Logging Configuration

This project uses a container-optimized logging configuration that supports both stdout and file logging.

## Features

- **Container-friendly**: Logs to stdout by default (required for containers/Airflow)
- **Optional file logging**: Logs to files if `LOG_DIR` is writable
- **Structured logging**: JSON format in container environments
- **Log rotation**: Automatic rotation of log files
- **Performance logging**: Built-in performance metrics logging
- **Context logging**: Support for additional context fields

## Environment Variables

Set these environment variables to configure logging:

```bash
# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO

# Directory for log files (optional)
LOG_DIR=/app/logs

# Application name for log file naming
APP_NAME=stock_data_app

# Enable/disable file logging (true/false)
ENABLE_FILE_LOGGING=true

# Container environment flag (set to true in containers for JSON logging)
CONTAINER_ENV=false
```

## Usage

### Basic Usage

```python
from logging_config import get_logger

logger = get_logger(__name__)

logger.info("Application started")
logger.error("An error occurred")
```

### Structured Logging

```python
from logging_config import log_with_context, log_performance

# Log with additional context
log_with_context(
    logger, 
    logging.INFO,
    "Processing stock data",
    ticker="AAPL",
    price=150.25,
    volume=1000000
)

# Log performance metrics
log_performance(
    logger,
    "data_scraping",
    duration=2.5,
    records_processed=100,
    success_rate=0.95
)
```

## Container Deployment

For container deployments (Docker, Kubernetes, Airflow):

```bash
# Set container environment for JSON logging
export CONTAINER_ENV=true
export LOG_LEVEL=INFO
export LOG_DIR=/app/logs  # Optional, for file logging
```

## Airflow Integration

The logging configuration is optimized for Airflow:

1. **Stdout logging**: All logs go to stdout, which Airflow captures
2. **Structured format**: JSON logs are easily parseable by log aggregation systems
3. **No file dependencies**: Works even if file system is read-only
4. **Performance metrics**: Built-in support for timing and metrics

## Log Levels

- **DEBUG**: Detailed information for debugging
- **INFO**: General information about program execution
- **WARNING**: Something unexpected happened, but the program is still working
- **ERROR**: A serious problem occurred
- **CRITICAL**: A very serious error occurred

## File Logging

If `LOG_DIR` is set and writable:
- Log files are created with rotation (10MB max, 5 backups)
- Files are named: `{APP_NAME}.log`
- Detailed formatting includes module, function, and line numbers

## Testing

Run the test script to verify logging configuration:

```bash
python test_logging.py
```

Test with different environments:

```bash
# Test with file logging
LOG_DIR=./logs python test_logging.py

# Test with JSON logging (container mode)
CONTAINER_ENV=true python test_logging.py

# Test with debug level
LOG_LEVEL=DEBUG python test_logging.py
```
