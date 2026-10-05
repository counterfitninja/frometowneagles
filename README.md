# Football Team Manager - Pterodactyl/Pelican Deployment

This is a Flask-based football team management application designed to run on Pterodactyl/Pelican game servers.

## Features
- Player management with ratings and retirement status (historic stats preserved)
- Retired players are excluded from upcoming team sheets, match selections and
  non-playing lists, including previously saved lineups. Past teams and recorded
  results are preserved; reactivating a player makes them eligible again.
- Match scheduling and team formations
- Drag-and-drop pitch interface
- Public pages for parents/players
- Click a player name on either public page to see upcoming non-playing dates without logging in (unselected teams are shown separately)
- Offline PWA support
- Team generator with shared rest-game rotation, per-goalkeeper in-goal targets and fixture-specific player availability
- One live match screen for the score, scorers, assists, substitutions and man of the match

## Match controls

Open **Matches > Live** for a specific fixture, or **Live** in the main navigation
for the next upcoming match. Tap **Goal!**, select the scorer, then the assister
(or **No assist**). The pitch and substitution controls stay on the same screen.
Matches without a selected team can still record results using active players.

Expand **Goals and assists** to review or remove goals. **More** contains result
sharing, man of the match, score corrections, whole-team switching and separate
resets for results and substitutions. Results are saved on the device and uploaded
when connected; the screen shows upload failures with a retry action. Existing
Match Day and Record Result links open the consolidated screen.

The main navigation keeps Home, Matches, Players and Live visible. Team generation,
saved formations, the leaderboard, settings and logout are under **More**. Each
fixture has Live and Plan team as its main actions; sharing and fixture edits are
under its **More** menu.

## Export player availability

In **Generate teams**, set each goalkeeper's target percentage (totalling 100%),
or leave all targets blank for equal rotation. Percentages apply to games **in goal**,
not total team selections, and are rounded to whole games across normal fixtures.
Keeper fixtures are randomised rather than allocated in consecutive blocks,
while respecting availability and the rounded targets. Random draws can still
produce consecutive games for the same keeper.
Keepers not assigned in goal are eligible for outfield places and share the same
rest-game balancing as all other players. Both in-goal and outfield appearances
count as playing; mandatory in-goal assignments take priority if they exceed a
keeper's fair share of games. If availability prevents meeting the targets,
generation reports an error so you can adjust them. **Invite all** fixtures include
all available players and do not count towards these targets. One keeper is assigned
in goal; others are marked outfield in the generated and saved team, without
changing their player profile. The summary separates in-goal, outfield and rest
games, including invite-all fixtures.

Generated teams are private. **Save private draft** stores a team and, when a
fixture is chosen, links it without exposing its selections on public pages.
Use **Matches > More > Publish team** to release it; **Make team private** hides
it again. To release them together, use **Generate teams > Make all games public**
and confirm. This publishes every saved private team, including past fixtures
and other seasons. Save generated teams to a fixture first; unsaved teams,
custom formations without a fixture, and games without a saved team are unchanged.
Managers can still edit private teams. Existing selected teams remain
published after upgrading. A custom-named formation without a fixture remains
manager-only; linking it later also creates a private draft requiring publication.

**Generate again** opens a review of every upcoming fixture in the current season,
from **1 September to 31 August**, including fixtures with saved teams. Review
the saved availability, team size and goalkeeper percentages, then confirm
**Generate again** to replace those teams with newly balanced private drafts.
The most recently used team size and keeper percentages are pre-filled.
Past fixtures, other seasons, results and saved player availability are kept.
Old formations are removed only if no other fixture uses them. New teams must
be published again using **Make all games public** or individually from Match
Schedule. If availability or keeper targets cannot
be satisfied, existing teams are left unchanged.

In **More > Generate teams**, select fixtures and tick the players who cannot
attend. All fixtures needing teams are selected by default, with no 20-game limit
for scheduled fixtures. Rest games are calculated automatically across the
selected fixtures using squad size, players per game and availability; unavailable
games do not count as rest games.
The generator also tries to avoid resting a player for two consecutive selected
fixtures, keeping total appearances balanced and respecting availability and
goalkeeper targets. This is a best-effort preference, not a guarantee; unavailable
games and invite-all appearances break a rest streak.
Use **Generate again** to replace existing teams
for every upcoming fixture in the current season. The number of teams comes
from the selected fixtures, not a manual game count. Add fixtures in
**Match Schedule** before generating teams.
Choose the generator's **More > Export availability (CSV)** to download
the current attendance selections without generating teams. The spreadsheet has
one row per active player per selected fixture, including player and fixture IDs,
date, opponent, location, position, and Available/Unavailable status. Unticked
players are treated as available, matching the team generator.

This exports the current form, not the saved playing/not-playing selections.

### Saved unavailability (kept when squads are reset)

Availability ticks are saved against each **player and date**, not the fixture,
so they survive saving or resetting squads. Ticks are saved automatically when you
**Generate teams**, or via the generator's **More > Save availability to players**.
They pre-fill the generator for any fixture on the same date. Manage them on the
**Players** page under **Saved unavailability** (add/remove dates per player), and
use **Export upcoming (CSV)** or **Export all, including past (CSV)** to download
them, even when no fixtures are left without a squad.

To restore them later, open the generator's **More** menu, choose the exported
file under **Availability CSV to import**, then select **Import availability CSV**.
The import replaces the selected fixtures and availability ticks with those in
the file; it does not generate teams or write attendance to the database.
You may edit the **Availability** column to `Available` or `Unavailable` before
importing. Keep the fixture/player IDs and every active player's row for each
fixture. UTF-8 CSV files up to 2 MB are supported. Invalid files, duplicate rows,
missing players and fixtures already assigned a formation are rejected without
applying any of the imported selections.

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
  - `/public/players/<player_id>` - A player's upcoming non-playing dates
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
