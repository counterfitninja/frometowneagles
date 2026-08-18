from flask import Flask, render_template, request, redirect, url_for, jsonify, session, send_file, abort
import sqlite3
from datetime import datetime, timezone, timedelta
import os
from functools import wraps
import hashlib

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')

# Security: Disable directory listing and restrict file access
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    return response

# Prevent direct database file access
@app.route('/football.db')
@app.route('/<path:filename>.db')
def block_database_access(filename=None):
    abort(403)

# Version number (GMT time)
def get_version():
    gmt = datetime.now(timezone.utc)
    return gmt.strftime('%Y%m%d.%H%M')

VERSION = get_version()

# Admin password - will be loaded from settings after DB init
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'eagles2026')

# Database path
DATABASE = os.environ.get('DATABASE_PATH', 'football.db')

# Ensure database is outside web-accessible directory
if not os.path.isabs(DATABASE):
    # Store database outside static/templates folders
    DATABASE = os.path.abspath(DATABASE)

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    global ADMIN_PASSWORD
    with get_db() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                position TEXT,
                rating INTEGER DEFAULT 3,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS formations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_date TEXT NOT NULL,
                opponent TEXT NOT NULL,
                location TEXT,
                formation_id INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (formation_id) REFERENCES formations(id)
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        
        # Set default team title if not exists
        existing = conn.execute("SELECT value FROM settings WHERE key = 'team_title'").fetchone()
        if not existing:
            conn.execute("INSERT INTO settings (key, value) VALUES ('team_title', 'Under-12 Football Manager')")
        
        conn.commit()

# Initialize database
init_db()

def get_setting(key, default=None):
    with get_db() as conn:
        result = conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return result['value'] if result else default

def set_setting(key, value):
    with get_db() as conn:
        conn.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, value))
        conn.commit()

def hash_password(password):
    """Hash a password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    """Verify a password against its hash"""
    return hash_password(password) == hashed

# Load password from database if stored there
def load_password_from_db():
    global ADMIN_PASSWORD
    stored_hash = get_setting('admin_password_hash')
    if stored_hash:
        # Store the hash so we can verify against it
        ADMIN_PASSWORD = stored_hash

# Load password from database after functions are defined
load_password_from_db()

@app.template_filter('ukdate')
def format_uk_date(date_string):
    """Convert YYYY-MM-DD to DD/MM/YYYY"""
    if not date_string:
        return ''
    try:
        # Parse the date string
        date_obj = datetime.strptime(date_string, '%Y-%m-%d')
        # Return in UK format
        return date_obj.strftime('%d/%m/%Y')
    except:
        return date_string

@app.context_processor
def inject_globals():
    """Make team_title available to all templates"""
    return {
        'team_title': get_setting('team_title', 'Under-12 Football Manager')
    }

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password = request.form.get('password')
        
        # Check if we're using a hashed password from DB or plain password from env
        stored_hash = get_setting('admin_password_hash')
        if stored_hash:
            # Verify against hash
            if verify_password(password, stored_hash):
                session['logged_in'] = True
                next_url = request.args.get('next')
                if not next_url:
                    return redirect(url_for('gameday'))
                return redirect(next_url)
        else:
            # Check against plain password from environment
            if password == ADMIN_PASSWORD:
                session['logged_in'] = True
                next_url = request.args.get('next')
                if not next_url:
                    return redirect(url_for('gameday'))
                return redirect(next_url)
        
        return render_template('login.html', error='Incorrect password', version=VERSION)
    return render_template('login.html', version=VERSION)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('index'))

@app.route('/')
def index():
    # If logged in, show manager dashboard, otherwise show public next match
    if session.get('logged_in'):
        return render_template('index.html', version=VERSION)
    else:
        return redirect(url_for('public_next_match'))

@app.route('/players')
@login_required
def players():
    with get_db() as conn:
        players_list = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
    return render_template('players.html', players=players_list, version=VERSION)

@app.route('/players/add', methods=['POST'])
@login_required
def add_player():
    name = request.form.get('name')
    position = request.form.get('position', '')
    rating = request.form.get('rating', 3, type=int)
    
    with get_db() as conn:
        conn.execute('INSERT INTO players (name, position, rating) VALUES (?, ?, ?)',
                    (name, position, rating))
        conn.commit()
    
    return redirect(url_for('players'))

@app.route('/players/<int:player_id>/delete', methods=['POST'])
@login_required
def delete_player(player_id):
    with get_db() as conn:
        conn.execute('DELETE FROM players WHERE id = ?', (player_id,))
        conn.commit()
    
    return redirect(url_for('players'))

@app.route('/players/<int:player_id>/edit', methods=['POST'])
@login_required
def edit_player(player_id):
    name = request.form.get('name')
    position = request.form.get('position', '')
    rating = request.form.get('rating', 3, type=int)
    
    with get_db() as conn:
        conn.execute('UPDATE players SET name = ?, position = ?, rating = ? WHERE id = ?',
                    (name, position, rating, player_id))
        conn.commit()
    
    return redirect(url_for('players'))

@app.route('/pitch')
@login_required
def pitch():
    # Clear any previous formation session data when loading pitch directly
    session.pop('loadFormation', None)
    session.pop('loadedMatchId', None)
    session.pop('loadedMatchName', None)
    session.pop('loadedMatchIdFromMatch', None)
    
    formation_id = request.args.get('formation_id', type=int)
    formation_data = None
    
    if formation_id:
        # Load formation data to pass to template
        import json
        with get_db() as conn:
            formation = conn.execute('SELECT * FROM formations WHERE id = ?', (formation_id,)).fetchone()
            if formation:
                try:
                    parsed_data = json.loads(formation['data'])
                    formation_data = {
                        'id': formation_id,
                        'name': formation['name'],
                        'data': parsed_data
                    }
                    print(f"Formation loaded: ID={formation_id}, Name={formation['name']}")
                except json.JSONDecodeError as e:
                    print(f"ERROR: Invalid JSON in formation {formation_id}: {e}")
                    # Set formation_data to None so page loads without formation
                    formation_data = None
    
    with get_db() as conn:
        players_list = conn.execute('SELECT * FROM players ORDER BY name').fetchall()

    import json as _json_pitch
    sub_counts = {}
    if formation_data:
        for formation in formation_data['data'].get('formations', []):
            for sub in formation.get('subs', []):
                pid = str(sub['id'])
                sub_counts[pid] = sub_counts.get(pid, 0) + 1

    return render_template('pitch.html', players=players_list, formation=formation_data, sub_counts=sub_counts, version=VERSION)

@app.route('/formations')
@login_required
def formations():
    with get_db() as conn:
        formations_list = conn.execute('SELECT * FROM formations ORDER BY created_at DESC').fetchall()
    return render_template('formations.html', formations=formations_list, version=VERSION)

@app.route('/api/matches/<int:match_id>/team')
@login_required
def api_match_team(match_id):
    import json
    with get_db() as conn:
        match = conn.execute('''
            SELECT m.*, f.data as formation_data
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id
            WHERE m.id = ?
        ''', (match_id,)).fetchone()
        all_players = conn.execute('SELECT * FROM players ORDER BY name').fetchall()

    if not match:
        return jsonify({'error': 'Match not found'}), 404

    match_dict = dict(match)
    if match_dict.get('formation_data'):
        formation_data = json.loads(match_dict['formation_data'])
        playing_ids = set()
        for formation in formation_data.get('formations', []):
            for p in formation.get('players', []):
                playing_ids.add(str(p['id']))
            for p in formation.get('subs', []):
                playing_ids.add(str(p['id']))
        playing = [dict(p) for p in all_players if str(p['id']) in playing_ids]
        not_playing = [dict(p) for p in all_players if str(p['id']) not in playing_ids]
    else:
        playing = []
        not_playing = [dict(p) for p in all_players]

    return jsonify({
        'match_date': match_dict['match_date'],
        'opponent': match_dict['opponent'],
        'location': match_dict['location'] or 'TBD',
        'playing': playing,
        'not_playing': not_playing
    })

@app.route('/api/formations')
@login_required
def api_formations():
    with get_db() as conn:
        formations_list = conn.execute('SELECT id, name, created_at FROM formations ORDER BY created_at DESC').fetchall()
    formations = [{'id': f['id'], 'name': f['name'], 'created_at': f['created_at'][:16]} for f in formations_list]
    return jsonify(formations)

@app.route('/formations/save', methods=['POST'])

@app.route('/formations/save', methods=['POST'])
@login_required
def save_formation():
    data = request.json
    name = data.get('name')
    formation_data = data.get('data')
    formation_id = data.get('id')  # For updating existing
    match_id = data.get('match_id')  # For linking to match
    
    with get_db() as conn:
        if formation_id:
            # Update existing formation
            conn.execute('UPDATE formations SET name = ?, data = ? WHERE id = ?',
                        (name, formation_data, formation_id))
            saved_id = formation_id
        else:
            # Create new formation
            cursor = conn.execute('INSERT INTO formations (name, data) VALUES (?, ?)',
                        (name, formation_data))
            saved_id = cursor.lastrowid
        
        # Link to match if match_id provided
        if match_id:
            conn.execute('UPDATE matches SET formation_id = ? WHERE id = ?',
                        (saved_id, match_id))
        
        conn.commit()
    
    return jsonify({'success': True, 'id': saved_id})

@app.route('/formations/<int:formation_id>/delete', methods=['POST'])
@login_required
def delete_formation(formation_id):
    with get_db() as conn:
        conn.execute('DELETE FROM formations WHERE id = ?', (formation_id,))
        conn.commit()
    
    return redirect(url_for('formations'))

@app.route('/formations/<int:formation_id>/load')
@login_required
def load_formation(formation_id):
    # Redirect to pitch with formation_id parameter instead of using session
    return redirect(url_for('pitch', formation_id=formation_id))

@app.route('/formations/<int:formation_id>/gameday')
@login_required
def gameday_view(formation_id):
    with get_db() as conn:
        formation = conn.execute('SELECT * FROM formations WHERE id = ?', (formation_id,)).fetchone()
    
    if formation:
        import json
        try:
            data = json.loads(formation['data'])
            formations_data = data.get('formations', [])
            
            # Safely handle created_at field
            created_at = formation['created_at'][:16] if formation['created_at'] else 'Unknown'
            
            return render_template('gameday.html', 
                                 formation_name=formation['name'],
                                 created_at=created_at,
                                 formations=formations_data,
                                 version=VERSION)
        except Exception as e:
            print(f"Error loading formation {formation_id}: {str(e)}")
            return f"Error loading formation: {str(e)}", 500
    
    return redirect(url_for('formations'))

@app.route('/formations/<int:formation_id>/live')
@login_required
def live_view(formation_id):
    import json as _json
    with get_db() as conn:
        row = conn.execute('''
            SELECT f.*, m.opponent, m.match_date, m.location
            FROM formations f
            LEFT JOIN matches m ON m.formation_id = f.id
            WHERE f.id = ?
        ''', (formation_id,)).fetchone()

    if not row:
        return redirect(url_for('formations'))

    try:
        data = _json.loads(row['data'])
        formations_data = data.get('formations', [])

        match_date_display = ''
        if row['match_date']:
            try:
                d = datetime.strptime(row['match_date'], '%Y-%m-%d')
                match_date_display = d.strftime('%a %d %b %Y')
            except Exception:
                match_date_display = row['match_date']

        return render_template('live.html',
                               formation_id=formation_id,
                               formation_name=row['name'],
                               formations_json=_json.dumps(formations_data),
                               opponent=row['opponent'] or 'Unknown',
                               match_date_display=match_date_display,
                               location=row['location'] or '',
                               version=VERSION)
    except Exception as e:
        print(f"Error loading live view {formation_id}: {str(e)}")
        return f"Error loading live view: {str(e)}", 500

@app.route('/formations/<int:formation_id>/matchday')
@login_required
def matchday_view(formation_id):
    import json as _json
    with get_db() as conn:
        row = conn.execute('''
            SELECT f.*, m.opponent, m.match_date, m.location
            FROM formations f
            LEFT JOIN matches m ON m.formation_id = f.id
            WHERE f.id = ?
        ''', (formation_id,)).fetchone()

    if not row:
        return redirect(url_for('formations'))

    try:
        data = _json.loads(row['data'])
    except Exception as e:
        print(f"Error loading match day {formation_id}: {str(e)}")
        return f"Error loading match day: {str(e)}", 500

    # Flatten every formation's players + subs into one squad list (unique by id)
    squad = []
    seen = set()
    for formation in data.get('formations', []):
        for player in list(formation.get('players', [])) + list(formation.get('subs', [])):
            pid = str(player.get('id'))
            if pid in seen:
                continue
            seen.add(pid)
            squad.append({
                'id': pid,
                'name': player.get('name', 'Unknown'),
                'position': player.get('position', '')
            })
    squad.sort(key=lambda p: p['name'])

    match_date_display = ''
    if row['match_date']:
        try:
            match_date_display = datetime.strptime(row['match_date'], '%Y-%m-%d').strftime('%a %d %b %Y')
        except Exception:
            match_date_display = row['match_date']

    return render_template('matchday.html',
                           formation_id=formation_id,
                           formation_name=row['name'],
                           squad_json=_json.dumps(squad),
                           opponent=row['opponent'] or 'Opponent',
                           match_date_display=match_date_display,
                           location=row['location'] or '',
                           version=VERSION)

@app.route('/matches')
@login_required
def matches():
    show_past = request.args.get('show_past', 'false').lower() == 'true'
    today = datetime.now().strftime('%Y-%m-%d')
    
    with get_db() as conn:
        if show_past:
            # Show all matches - oldest first
            matches_list = conn.execute('''
                SELECT m.*, f.name as formation_name 
                FROM matches m
                LEFT JOIN formations f ON m.formation_id = f.id
                ORDER BY m.match_date ASC
            ''').fetchall()
        else:
            # Show only upcoming matches (today and future)
            matches_list = conn.execute('''
                SELECT m.*, f.name as formation_name 
                FROM matches m
                LEFT JOIN formations f ON m.formation_id = f.id
                WHERE m.match_date >= ?
                ORDER BY m.match_date ASC
            ''', (today,)).fetchall()
    
    matches = [dict(m) for m in matches_list]
    return render_template('matches.html', matches=matches, show_past=show_past, version=VERSION)

@app.route('/matches/overview')
@login_required
def matches_overview():
    import json
    
    with get_db() as conn:
        # Get all matches with formations
        matches_list = conn.execute('''
            SELECT m.*, f.data as formation_data
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id
            WHERE m.formation_id IS NOT NULL
            ORDER BY m.match_date
        ''').fetchall()
        
        # Get all players
        all_players = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
    
    # Process each match
    matches_with_teams = []
    for match in matches_list:
        match_dict = dict(match)
        
        if match_dict['formation_data']:
            formation_data = json.loads(match_dict['formation_data'])
            
            # Get players in formations
            playing_player_ids = set()
            if 'formations' in formation_data:
                for formation in formation_data['formations']:
                    for player in formation.get('players', []):
                        playing_player_ids.add(str(player['id']))
                    for sub in formation.get('subs', []):
                        playing_player_ids.add(str(sub['id']))
            
            print(f"Match: {match_dict['opponent']}, Playing IDs: {playing_player_ids}")
            
            # Separate playing vs not playing
            playing = [dict(p) for p in all_players if str(p['id']) in playing_player_ids]
            not_playing = [dict(p) for p in all_players if str(p['id']) not in playing_player_ids]
            
            print(f"  Playing: {len(playing)}, Not Playing: {len(not_playing)}")
            if not_playing:
                print(f"  Not playing: {[p['name'] for p in not_playing]}")
            
            match_dict['playing'] = playing
            match_dict['not_playing'] = not_playing
        else:
            match_dict['playing'] = []
            match_dict['not_playing'] = [dict(p) for p in all_players]
        
        matches_with_teams.append(match_dict)
    
    # Calculate player statistics across all matches
    from collections import defaultdict
    player_stats = defaultdict(lambda: {'playing': 0, 'not_playing': 0, 'name': '', 'position': ''})
    
    for player in all_players:
        player_id = str(player['id'])
        player_stats[player_id]['name'] = player['name']
        player_stats[player_id]['position'] = player['position']
    
    for match in matches_with_teams:
        for player in match['playing']:
            player_stats[str(player['id'])]['playing'] += 1
        for player in match['not_playing']:
            player_stats[str(player['id'])]['not_playing'] += 1
    
    # Convert to sorted list
    stats_list = sorted(player_stats.values(), key=lambda x: x['name'])
    
    print(f"Player stats calculated: {len(stats_list)} players")
    for stat in stats_list:
        print(f"  {stat['name']}: Playing={stat['playing']}, Not Playing={stat['not_playing']}")
    
    return render_template('matches_overview.html', 
                         matches=matches_with_teams,
                         player_stats=stats_list,
                         version=VERSION)

@app.route('/matches/overview/text')
@login_required
def matches_overview_text():
    import json
    
    with get_db() as conn:
        # Get all matches with formations
        matches_list = conn.execute('''
            SELECT m.*, f.data as formation_data
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id
            WHERE m.formation_id IS NOT NULL
            ORDER BY m.match_date
        ''').fetchall()
        
        # Get all players
        all_players = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
    
    # Build text output
    text_output = "⚽ UPCOMING MATCHES - TEAM SELECTIONS ⚽\n"
    text_output += "=" * 45 + "\n\n"
    
    for match in matches_list:
        match_dict = dict(match)
        text_output += f"📅 {match_dict['match_date']} - vs {match_dict['opponent']}\n"
        text_output += f"📍 {match_dict['location'] or 'TBD'}\n"
        text_output += "-" * 45 + "\n"
        
        if match_dict['formation_data']:
            formation_data = json.loads(match_dict['formation_data'])
            
            # Get players in formations
            playing_player_ids = set()
            if 'formations' in formation_data:
                for formation in formation_data['formations']:
                    for player in formation.get('players', []):
                        playing_player_ids.add(str(player['id']))
                    for sub in formation.get('subs', []):
                        playing_player_ids.add(str(sub['id']))
            
            # Separate playing vs not playing
            playing = [dict(p) for p in all_players if str(p['id']) in playing_player_ids]
            not_playing = [dict(p) for p in all_players if str(p['id']) not in playing_player_ids]
            
            text_output += f"\n✅ PLAYING ({len(playing)}):\n"
            for player in sorted(playing, key=lambda x: x['name']):
                gk_icon = " 🧤" if player['position'] == 'GK' else ""
                text_output += f"  • {player['name']}{gk_icon}\n"
            
            if not_playing:
                text_output += f"\n❌ NOT PLAYING ({len(not_playing)}):\n"
                for player in sorted(not_playing, key=lambda x: x['name']):
                    gk_icon = " 🧤" if player['position'] == 'GK' else ""
                    text_output += f"  • {player['name']}{gk_icon}\n"
        else:
            text_output += "\n⚠️ No team selected for this match\n"
        
        text_output += "\n" + "=" * 45 + "\n\n"
    
    if not matches_list:
        text_output += "No matches with teams found.\n"
    
    return text_output, 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/public/next-match')
def public_next_match():
    """Public page showing the next upcoming match and all upcoming matches"""
    import json
    today = datetime.now().strftime('%Y-%m-%d')

    with get_db() as conn:
        # Find all upcoming matches (today or later)
        upcoming = conn.execute('''
            SELECT m.*, f.data as formation_data, f.name as formation_name
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id
            WHERE m.match_date >= ?
            ORDER BY m.match_date ASC
        ''', (today,)).fetchall()

        # Get all players
        all_players = conn.execute('SELECT * FROM players ORDER BY name').fetchall()

    if not upcoming:
        return render_template('public_next_match.html', match=None, upcoming_matches=[], version=VERSION)

    def process_match(raw_match):
        match_dict = dict(raw_match)
        if match_dict['formation_data']:
            formation_data = json.loads(match_dict['formation_data'])
            playing_player_ids = set()
            if 'formations' in formation_data:
                for formation in formation_data['formations']:
                    for player in formation.get('players', []):
                        playing_player_ids.add(str(player['id']))
                    for sub in formation.get('subs', []):
                        playing_player_ids.add(str(sub['id']))
            playing = [dict(p) for p in all_players if str(p['id']) in playing_player_ids]
            not_playing = [dict(p) for p in all_players if str(p['id']) not in playing_player_ids]
            match_dict['playing'] = sorted(playing, key=lambda x: x['name'])
            match_dict['not_playing'] = sorted(not_playing, key=lambda x: x['name'])
        else:
            match_dict['playing'] = []
            match_dict['not_playing'] = []
        return match_dict

    all_upcoming = [process_match(m) for m in upcoming]
    next_match = all_upcoming[0]
    future_matches = all_upcoming[1:]

    return render_template('public_next_match.html', match=next_match, upcoming_matches=future_matches, version=VERSION)

@app.route('/public/overview')
def public_overview():
    """Public page showing all matches overview"""
    import json
    
    with get_db() as conn:
        # Get all matches with formations
        matches_list = conn.execute('''
            SELECT m.*, f.data as formation_data
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id
            WHERE m.formation_id IS NOT NULL
            ORDER BY m.match_date
        ''').fetchall()
        
        # Get all players
        all_players = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
    
    # Process each match
    matches_with_teams = []
    for match in matches_list:
        match_dict = dict(match)
        
        if match_dict['formation_data']:
            formation_data = json.loads(match_dict['formation_data'])
            
            # Get players in formations
            playing_player_ids = set()
            if 'formations' in formation_data:
                for formation in formation_data['formations']:
                    for player in formation.get('players', []):
                        playing_player_ids.add(str(player['id']))
                    for sub in formation.get('subs', []):
                        playing_player_ids.add(str(sub['id']))
            
            # Separate playing vs not playing
            playing = [dict(p) for p in all_players if str(p['id']) in playing_player_ids]
            not_playing = [dict(p) for p in all_players if str(p['id']) not in playing_player_ids]
            
            match_dict['playing'] = sorted(playing, key=lambda x: x['name'])
            match_dict['not_playing'] = sorted(not_playing, key=lambda x: x['name'])
        else:
            match_dict['playing'] = []
            match_dict['not_playing'] = [dict(p) for p in all_players]
        
        matches_with_teams.append(match_dict)
    
    # Calculate player statistics across all matches
    from collections import defaultdict
    player_stats = defaultdict(lambda: {'playing': 0, 'not_playing': 0, 'name': '', 'position': ''})
    
    for player in all_players:
        player_id = str(player['id'])
        player_stats[player_id]['name'] = player['name']
        player_stats[player_id]['position'] = player['position']
    
    for match in matches_with_teams:
        for player in match['playing']:
            player_stats[str(player['id'])]['playing'] += 1
        for player in match['not_playing']:
            player_stats[str(player['id'])]['not_playing'] += 1
    
    # Convert to sorted list
    stats_list = sorted(player_stats.values(), key=lambda x: x['name'])
    
    return render_template('public_overview.html', 
                         matches=matches_with_teams, 
                         player_stats=stats_list,
                         version=VERSION)

@app.route('/gameday')
@login_required
def gameday():
    """Redirect to the next upcoming match's formation page"""
    today = datetime.now().strftime('%Y-%m-%d')
    
    with get_db() as conn:
        # Find the next upcoming match (today or later)
        next_match = conn.execute('''
            SELECT * FROM matches 
            WHERE match_date >= ? 
            ORDER BY match_date ASC 
            LIMIT 1
        ''', (today,)).fetchone()
        
        if next_match:
            match_dict = dict(next_match)
            # If match has a formation, edit it; otherwise create one
            if match_dict['formation_id']:
                return redirect(url_for('pitch', formation_id=match_dict['formation_id']))
            else:
                match_name = f"{match_dict['match_date']} - vs {match_dict['opponent']}"
                return redirect(url_for('pitch', match_id=match_dict['id'], match_name=match_name))
        else:
            # No upcoming matches, redirect to matches page
            return redirect(url_for('matches'))

@app.route('/live')
@login_required
def live_shortcut():
    """Redirect to the next upcoming match's live view (must have a formation)"""
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db() as conn:
        next_match = conn.execute('''
            SELECT * FROM matches
            WHERE match_date >= ? AND formation_id IS NOT NULL
            ORDER BY match_date ASC
            LIMIT 1
        ''', (today,)).fetchone()
    if next_match:
        return redirect(url_for('live_view', formation_id=dict(next_match)['formation_id']))
    return redirect(url_for('matches'))

@app.route('/matches/add', methods=['POST'])
@login_required
def add_match():
    match_date = request.form.get('match_date')
    opponent = request.form.get('opponent')
    location = request.form.get('location', 'TBD')
    
    if not match_date or not opponent:
        return redirect(url_for('matches', error='Date and opponent are required'))
    
    try:
        # Validate date format
        datetime.strptime(match_date, '%Y-%m-%d')
        
        with get_db() as conn:
            conn.execute('''
                INSERT INTO matches (match_date, opponent, location)
                VALUES (?, ?, ?)
            ''', (match_date, opponent, location))
            conn.commit()
        
        return redirect(url_for('matches'))
    except ValueError:
        return redirect(url_for('matches', error='Invalid date format'))
    except Exception as e:
        return redirect(url_for('matches', error=str(e)))

@app.route('/matches/edit', methods=['POST'])
@login_required
def edit_match():
    match_id = request.form.get('match_id')
    match_date = request.form.get('match_date')
    opponent = request.form.get('opponent')
    location = request.form.get('location', 'TBD')
    
    if not match_id or not match_date or not opponent:
        return redirect(url_for('matches', error='All fields are required'))
    
    try:
        # Validate date format
        datetime.strptime(match_date, '%Y-%m-%d')
        
        with get_db() as conn:
            conn.execute('''
                UPDATE matches 
                SET match_date = ?, opponent = ?, location = ?
                WHERE id = ?
            ''', (match_date, opponent, location, match_id))
            conn.commit()
        
        return redirect(url_for('matches'))
    except ValueError:
        return redirect(url_for('matches', error='Invalid date format'))
    except Exception as e:
        return redirect(url_for('matches', error=str(e)))

@app.route('/matches/bulk-upload', methods=['POST'])
@login_required
def bulk_upload_matches():
    matches_text = request.form.get('matches_text', '')
    
    if not matches_text.strip():
        return jsonify({'success': False, 'error': 'No matches provided'})
    
    lines = [line.strip() for line in matches_text.strip().split('\n') if line.strip()]
    added_matches = []
    errors = []
    
    with get_db() as conn:
        for i, line in enumerate(lines, 1):
            try:
                # Expected format: "YYYY-MM-DD | Opponent | Location"
                parts = [p.strip() for p in line.split('|')]
                if len(parts) < 2:
                    errors.append(f'Line {i}: Invalid format (need at least date | opponent)')
                    continue
                
                match_date = parts[0]
                opponent = parts[1]
                location = parts[2] if len(parts) > 2 else 'TBD'
                
                # Validate date format
                datetime.strptime(match_date, '%Y-%m-%d')
                
                conn.execute('''
                    INSERT INTO matches (match_date, opponent, location)
                    VALUES (?, ?, ?)
                ''', (match_date, opponent, location))
                
                added_matches.append({'date': match_date, 'opponent': opponent, 'location': location})
            except ValueError as e:
                errors.append(f'Line {i}: Invalid date format (use YYYY-MM-DD)')
            except Exception as e:
                errors.append(f'Line {i}: {str(e)}')
        
        conn.commit()
    
    return jsonify({
        'success': True,
        'added': len(added_matches),
        'errors': errors,
        'matches': added_matches
    })

@app.route('/matches/<int:match_id>/delete', methods=['POST'])
@login_required
def delete_match(match_id):
    with get_db() as conn:
        conn.execute('DELETE FROM matches WHERE id = ?', (match_id,))
        conn.commit()
    return jsonify({'success': True})

@app.route('/matches/<int:match_id>/link-formation/<int:formation_id>', methods=['POST'])
@login_required
def link_formation_to_match(match_id, formation_id):
    with get_db() as conn:
        conn.execute('UPDATE matches SET formation_id = ? WHERE id = ?', (formation_id, match_id))
        conn.commit()
    return jsonify({'success': True})

@app.route('/team-generator')
@login_required
def team_generator():
    with get_db() as conn:
        players_list = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
        # Get matches without formations
        matches_list = conn.execute('''
            SELECT id, match_date, opponent, location 
            FROM matches 
            WHERE formation_id IS NULL 
            ORDER BY match_date
        ''').fetchall()
    
    players = [dict(p) for p in players_list]
    matches = [dict(m) for m in matches_list]
    return render_template('team_generator.html', players=players, matches=matches, version=VERSION)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    success = request.args.get('success')
    error = request.args.get('error')
    
    if request.method == 'POST':
        team_title = request.form.get('team_title', '').strip()
        if team_title:
            set_setting('team_title', team_title)
            return redirect(url_for('settings', success='Settings saved successfully'))
    
    team_title = get_setting('team_title', 'Under-12 Football Manager')
    return render_template('settings.html', team_title=team_title, version=VERSION, success=success, error=error)

@app.route('/settings/change-password', methods=['POST'])
@login_required
def change_password():
    global ADMIN_PASSWORD
    
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    # Verify current password
    stored_hash = get_setting('admin_password_hash')
    if stored_hash:
        # Verify against hash
        if not verify_password(current_password, stored_hash):
            return redirect(url_for('settings', error='Current password is incorrect'))
    else:
        # Check against plain password from environment
        if current_password != ADMIN_PASSWORD:
            return redirect(url_for('settings', error='Current password is incorrect'))
    
    # Validate new password
    if len(new_password) < 6:
        return redirect(url_for('settings', error='New password must be at least 6 characters'))
    
    if new_password != confirm_password:
        return redirect(url_for('settings', error='New passwords do not match'))
    
    # Hash and store the new password
    password_hash = hash_password(new_password)
    set_setting('admin_password_hash', password_hash)
    
    # Update global variable with hash for this session
    ADMIN_PASSWORD = password_hash
    
    return redirect(url_for('settings', success='Password updated successfully and encrypted in database!'))

@app.route('/team-generator/generate', methods=['POST'])
@login_required
def generate_teams():
    import json
    import random
    from collections import defaultdict
    
    num_games = int(request.form.get('num_games', 4))
    team_size = int(request.form.get('team_size', 11))
    
    # Get all players
    with get_db() as conn:
        players_list = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
    
    if len(players_list) < team_size:
        return render_template('team_generator.html', 
                             error=f'Not enough players! You have {len(players_list)} players but need at least {team_size}.',
                             version=VERSION)
    
    # Convert to list of dicts
    players = [dict(p) for p in players_list]
    
    # Randomize player order at start to ensure different results each time
    random.shuffle(players)
    
    # Separate goalkeepers and outfield players
    goalkeepers = [p for p in players if p['position'] == 'GK']
    outfield = [p for p in players if p['position'] != 'GK']
    
    if len(goalkeepers) == 0:
        return render_template('team_generator.html', 
                             error='No goalkeepers found! Please add at least one player with position "GK".',
                             version=VERSION)
    
    # Generate teams
    teams = []
    player_game_count = defaultdict(int)  # Track how many games each player plays
    
    for game in range(num_games):
        # Calculate how many players we need
        starters_needed = 9
        subs_needed = team_size - 9
        
        # Sort players by games played (least to most), with random tiebreaker
        sorted_players = sorted(players, key=lambda p: (player_game_count[p['id']], random.random()))
        
        # Pick goalkeepers first - ensure at least 1, but allow 2 if available
        team_gks = []
        available_gks = [gk for gk in goalkeepers if player_game_count[gk['id']] < num_games]
        
        if len(available_gks) >= 2:
            # Take the 2 goalkeepers with least games, randomize if tied
            team_gks = sorted(available_gks, key=lambda p: (player_game_count[p['id']], random.random()))[:2]
        elif len(available_gks) >= 1:
            team_gks = [available_gks[0]]
        else:
            # All goalkeepers have played all games, just pick one randomly
            team_gks = [random.choice(goalkeepers)]
        
        # Pick outfield players
        available_outfield = [p for p in outfield]
        
        # Calculate remaining spots
        remaining_spots = team_size - len(team_gks)
        
        # Pick players with least games first, randomize within same game count
        team_outfield = sorted(available_outfield, key=lambda p: (player_game_count[p['id']], random.random()))[:remaining_spots]
        
        # Combine team
        full_team = team_gks + team_outfield
        random.shuffle(full_team)  # Randomize order within team
        
        # Ensure at least 1 GK in starters
        starters = []
        subs = []
        
        # Put one GK in starters
        gk_in_starters = [p for p in full_team if p['position'] == 'GK'][0]
        starters.append(gk_in_starters)
        remaining = [p for p in full_team if p['id'] != gk_in_starters['id']]
        
        # Fill remaining starters (8 more to make 9)
        starters.extend(remaining[:8])
        
        # Rest are subs
        subs = remaining[8:]
        
        # Update game counts
        for p in full_team:
            player_game_count[p['id']] += 1
        
        # Find players not in this game
        team_player_ids = set([p['id'] for p in full_team])
        not_playing = [p for p in players if p['id'] not in team_player_ids]
        
        teams.append({
            'starters': starters,
            'subs': subs,
            'not_playing': not_playing
        })
    
    # Calculate stats
    max_games_missed = max([num_games - player_game_count[p['id']] for p in players])
    
    stats = {
        'total_players': len(players),
        'num_games': num_games,
        'team_size': team_size,
        'max_games_missed': max_games_missed
    }
    
    # Get available matches for linking
    with get_db() as conn:
        matches_list = conn.execute('''
            SELECT id, match_date, opponent, location 
            FROM matches 
            WHERE formation_id IS NULL 
            ORDER BY match_date
        ''').fetchall()
    matches = [dict(m) for m in matches_list]
    
    return render_template('team_generator.html', 
                         teams=teams, 
                         stats=stats,
                         players=players,
                         matches=matches,
                         version=VERSION)

if __name__ == '__main__':
    init_db()
    load_password_from_db()
    port = int(os.environ.get('PORT', 8081))
    app.run(host='0.0.0.0', port=port, debug=True)
