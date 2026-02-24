#!/bin/bash
# Development server startup
# For production, use startup.sh with gunicorn

PORT=${PORT:-5000}
python app.py
