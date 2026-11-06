# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies. GH_PAT (needed to install
# the private stocker_metrics package) is mounted as a BuildKit secret so it is
# never written to an image layer or visible via `docker history`.
COPY requirements.txt .
RUN --mount=type=secret,id=gh_pat \
    git config --global url."https://$(cat /run/secrets/gh_pat)@github.com/".insteadOf "https://github.com/" \
    && pip install --no-cache-dir -r requirements.txt \
    && git config --global --unset-all url."https://$(cat /run/secrets/gh_pat)@github.com/".insteadOf

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
CMD ["python", "main.py"]
