#!/bin/bash
set -e

# Use dynamic PORT provided by Render / Railway, defaulting to 8501
PORT="${PORT:-8501}"
echo "Starting AI Trading OS Workstation on port ${PORT}..."

# Ensure persistent storage subdirectories exist
mkdir -p "${TRADINGOS_DATA_DIR:-/app/data}/screenshots"
mkdir -p "${TRADINGOS_DATA_DIR:-/app/data}/backups"
mkdir -p "${TRADINGOS_DATA_DIR:-/app/data}/cache"

exec streamlit run app.py \
    --server.port="${PORT}" \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --browser.gatherUsageStats=false
