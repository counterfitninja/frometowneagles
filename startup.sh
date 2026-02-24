#!/bin/bash
# Startup script for Pterodactyl/Pelican game server
# Use PORT from environment, default to 5000 if not set
export PORT=${PORT:-8081}
echo "Starting server on port: $PORT"

# Secure the database file permissions
if [ -f "football.db" ]; then
    chmod 600 football.db
    echo "Database file permissions secured"
fi

gunicorn --bind=0.0.0.0:$PORT --timeout 600 --workers 2 app:app
