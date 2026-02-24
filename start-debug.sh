#!/bin/bash
# Alternative startup script with explicit port handling

# Debug: Show what PORT is set to
echo "Environment PORT variable: ${PORT}"
echo "All environment variables:"
env | grep -i port

# Set port with fallback
if [ -z "$PORT" ]; then
    echo "WARNING: PORT not set, using default 8081"
    PORT=8081
fi

echo "Starting Flask application on 0.0.0.0:${PORT}"
gunicorn --bind=0.0.0.0:${PORT} --timeout 600 --workers 2 --log-level debug app:app
