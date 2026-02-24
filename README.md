# Football Team Manager - Pterodactyl/Pelican Deployment

This is a Flask-based football team management application designed to run on Pterodactyl/Pelican game servers.

## Features
- Player management with ratings
- Match scheduling and team formations
- Drag-and-drop pitch interface
- Public pages for parents/players
- Offline PWA support
- Team generator with balanced selection

## Requirements
- Python 3.8+
- Flask 3.0.0
- Gunicorn 21.2.0
- SQLite (included with Python)

## Installation on Pterodactyl/Pelican

### 1. Create Python Egg Server
Create a new server using the Python generic egg or Flask egg.

### 2. Upload Files
Upload all project files to your server directory.

### 3. Set Environment Variables
Configure these in your Pterodactyl panel:

- `PORT` - Port to run on (usually auto-set by Pterodactyl)
- `ADMIN_PASSWORD` - Your admin password (default: eagles2026)
- `SECRET_KEY` - Flask secret key for sessions (generate a random string)
- `DATABASE_PATH` - Path to SQLite database (default: football.db)

### 4. Startup Command
Use one of these startup commands:

**Production (recommended):**
```bash
bash startup.sh
```

**Development:**
```bash
python app.py
```

## Configuration

### Change Admin Password
Set the `ADMIN_PASSWORD` environment variable in Pterodactyl panel.

### Team Title
After logging in, go to Settings to change the team title (e.g., "Under-13 Football Manager").

### Database Location
By default, the database is stored as `football.db` in the working directory.
To use a different path, set the `DATABASE_PATH` environment variable.

## Default Access
- **Login**: Visit your server URL
- **Public Pages**: 
  - `/public/next-match` - Next upcoming match
  - `/public/overview` - All matches overview
- **Default Password**: Set via `ADMIN_PASSWORD` environment variable

## File Structure
```
.
├── app.py                      # Main Flask application
├── startup.sh                  # Production startup script (gunicorn)
├── start-debug.sh              # Debug startup script
├── run.sh                      # Development startup script
├── Procfile                    # Deployment entry point
├── requirements.txt            # Python dependencies
├── egg-frometowneagles.json    # Pelican/Pterodactyl egg
├── football.db                 # SQLite database (created on first run)
├── static/                     # Static assets (CSS, JS, PWA)
└── templates/                  # HTML templates
```

## Port Configuration
The application uses the `PORT` environment variable (default: 5000).
Pterodactyl will automatically set this when you allocate a port to your server.

### Troubleshooting Port Issues

If the application starts on port 5000 instead of your allocated port:

1. **Check Console Output**: Look for the line "Starting server on port: X"
   - If it shows 5000, the PORT variable isn't being passed correctly

2. **Try Debug Startup Script**:
   ```bash
   bash start-debug.sh
   ```
   This will show all environment variables and help diagnose the issue.

3. **Manually Set PORT in Startup Command**:
   In Pelican panel, go to Startup tab and modify the startup command:
   ```bash
   PORT={{SERVER_PORT}} bash startup.sh
   ```
   Or use your specific port:
   ```bash
   PORT=8081 bash startup.sh
   ```

4. **Check Pelican Variable Mapping**:
   - Verify that `{{SERVER_PORT}}` is mapped to your allocated port
   - Check if there's a PORT variable already defined in the Startup Variables section

5. **Alternative: Hardcode Port Temporarily**:
   Edit `startup.sh` and replace the first line with:
   ```bash
   export PORT=8081  # Replace with your port
   ```

## Database Persistence
The SQLite database (`football.db`) stores all data:
- Players
- Matches
- Formations
- Settings

**Important**: Make sure your Pterodactyl server has persistent storage configured
to prevent data loss on restarts.

## Accessing the Application
Once started, access your application at:
```
http://your-server-ip:PORT
```

Or if using a domain:
```
http://your-domain.com
```

## Troubleshooting

### Port Already in Use
Check if another application is using the port. Change the port allocation in Pterodactyl.

### Database Errors
Ensure the application has write permissions to the directory where `football.db` is stored.

### Import Errors
Run: `pip install -r requirements.txt`

### Can't Access Public Pages
Make sure you're using the correct URL paths:
- `/public/next-match`
- `/public/overview`

## Support
This application requires no external services and runs entirely self-contained
with SQLite for data storage.

## Security Notes

### Database Protection
The application includes multiple layers of database security:
1. **HTTP Route Blocking**: Direct access to `.db` files via HTTP is blocked (returns 403)
2. **File Permissions**: Database file is set to 600 (owner read/write only) on startup
3. **Security Headers**: X-Frame-Options, X-Content-Type-Options, and XSS protection enabled
4. **.htaccess Protection**: Apache servers will deny access to database, Python, and config files

### Password Security
1. **Change the default password** immediately after first login via Settings page
2. Passwords are hashed using SHA-256 before storage in database
3. Set `ADMIN_PASSWORD` environment variable in Pelican for additional security
4. Use a strong password with minimum 6 characters

### Additional Security Measures
1. Set a secure random `SECRET_KEY` environment variable
2. Use HTTPS in production (configure via reverse proxy)
3. Public pages are accessible without authentication by design (for parents/players)
4. Database is stored with restricted file permissions (chmod 600)
5. Store database outside web root if possible using `DATABASE_PATH` environment variable

### File Access
If using a reverse proxy (nginx/Apache), ensure these paths are blocked:
- `*.db`, `*.sqlite`, `*.sqlite3` - Database files
- `*.py`, `*.pyc`, `*.pyo` - Python source files
- `*.env`, `*.log`, `*.ini` - Config and log files
