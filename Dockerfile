FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p /app/logs

# Set environment variables for container
ENV CONTAINER_ENV=true
ENV LOG_LEVEL=INFO
ENV LOG_DIR=/app/logs
ENV APP_NAME=stock_data_app
ENV PYTHONUNBUFFERED=1

# Uses dev.json from the image. Override `command` in compose for prod + CLI flags.
CMD ["sh", "python", "main.py"]
