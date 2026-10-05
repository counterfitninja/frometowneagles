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
    if request.path == '/static/sw.js':
        response.headers['Service-Worker-Allowed'] = '/'
    if request.path.startswith('/team-generator'):
        response.headers.setdefault('Cache-Control', 'private, no-store')
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
                status TEXT NOT NULL DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # Existing installations need the lifecycle column added without losing players.
        player_columns = {column['name'] for column in conn.execute('PRAGMA table_info(players)').fetchall()}
        if 'status' not in player_columns:
            conn.execute("ALTER TABLE players ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        
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
        formation_columns = {column['name'] for column in conn.execute('PRAGMA table_info(formations)').fetchall()}
        if 'private_team' not in formation_columns:
            conn.execute('ALTER TABLE formations ADD COLUMN private_team INTEGER NOT NULL DEFAULT 0')

        conn.execute('''
            CREATE TABLE IF NOT EXISTS match_results (
                match_id INTEGER PRIMARY KEY,
                goals_json TEXT NOT NULL DEFAULT '[]',
                opponent_goals INTEGER NOT NULL DEFAULT 0,
                motm_player_id INTEGER,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (match_id) REFERENCES matches(id) ON DELETE CASCADE,
                FOREIGN KEY (motm_player_id) REFERENCES players(id)
            )
        ''')
        match_columns = {column['name'] for column in conn.execute('PRAGMA table_info(matches)').fetchall()}
        if 'team_published' not in match_columns:
            conn.execute('ALTER TABLE matches ADD COLUMN team_published INTEGER NOT NULL DEFAULT 1')
        
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
        players_list = conn.execute('''
            SELECT * FROM players
            ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, name
        ''').fetchall()
    return render_template('players.html', players=players_list, version=VERSION)

@app.route('/stats')
@login_required
def stats():
    import json
    from collections import defaultdict

    with get_db() as conn:
        players_list = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
        results = conn.execute('''
            SELECT mr.*, m.match_date, m.opponent, m.location, p.name as motm_name
            FROM match_results mr
            JOIN matches m ON m.id = mr.match_id
            LEFT JOIN players p ON p.id = mr.motm_player_id
            ORDER BY m.match_date DESC, m.id DESC
        ''').fetchall()

    players_by_id = {str(player['id']): dict(player) for player in players_list}
    players_by_name = {player['name']: dict(player) for player in players_list}
    player_stats = defaultdict(lambda: {
        'id': None,
        'name': 'Unknown',
        'position': '',
        'status': 'active',
        'goals': 0,
        'assists': 0,
        'motm': 0
    })

    for player in players_list:
        player_id = str(player['id'])
        player_stats[player_id].update({
            'id': player['id'],
            'name': player['name'],
            'position': player['position'] or '',
            'status': player['status']
        })

    matches_with_results = []
    total_goals = 0
    total_assists = 0

    for result in results:
        try:
            goals = json.loads(result['goals_json'] or '[]')
        except json.JSONDecodeError:
            goals = []

        for goal in goals:
            scorer_key = str(goal.get('scorer_id') or '')
            if not scorer_key and goal.get('scorer') in players_by_name:
                scorer_key = str(players_by_name[goal['scorer']]['id'])

            if scorer_key:
                player = players_by_id.get(scorer_key)
                if player:
                    player_stats[scorer_key].update({
                        'id': player['id'],
                        'name': player['name'],
                        'position': player['position'] or '',
                        'status': player['status']
                    })
                player_stats[scorer_key]['goals'] += 1
                total_goals += 1

            assist_key = str(goal.get('assist_id') or '')
            if not assist_key and goal.get('assist') in players_by_name:
                assist_key = str(players_by_name[goal['assist']]['id'])

            if assist_key:
                player = players_by_id.get(assist_key)
                if player:
                    player_stats[assist_key].update({
                        'id': player['id'],
                        'name': player['name'],
                        'position': player['position'] or '',
                        'status': player['status']
                    })
                player_stats[assist_key]['assists'] += 1
                total_assists += 1

        if result['motm_player_id']:
            motm_key = str(result['motm_player_id'])
            if motm_key in players_by_id:
                player_stats[motm_key]['motm'] += 1

        matches_with_results.append({
            'match_date': result['match_date'],
            'opponent': result['opponent'],
            'location': result['location'] or 'TBD',
            'our_goals': len(goals),
            'opponent_goals': result['opponent_goals'],
            'motm_name': result['motm_name'],
            'has_result': bool(goals or result['opponent_goals'] or result['motm_player_id'])
        })

    leaderboard = sorted(
        player_stats.values(),
        key=lambda stat: (-stat['goals'], -stat['assists'], -stat['motm'], stat['name'])
    )

    return render_template('stats.html',
                           leaderboard=leaderboard,
                           matches=matches_with_results,
                           team_title=get_setting('team_title', 'Under-12 Football Manager'),
                           totals={
                               'goals': total_goals,
                               'assists': total_assists,
                               'motm': sum(1 for match in matches_with_results if match['motm_name'])
                           },
                           version=VERSION)

@app.route('/players/add', methods=['POST'])
@login_required
def add_player():
    name = request.form.get('name')
    position = request.form.get('position', '')
    rating = request.form.get('rating', 3, type=int)
    
    with get_db() as conn:
        conn.execute('INSERT INTO players (name, position, rating, status) VALUES (?, ?, ?, ?)',
                    (name, position, rating, 'active'))
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
    status = request.form.get('status', 'active')
    if status not in {'active', 'retired'}:
        status = 'active'
    
    with get_db() as conn:
        conn.execute('''
            UPDATE players
            SET name = ?, position = ?, rating = ?, status = ?
            WHERE id = ?
        ''', (name, position, rating, status, player_id))
        conn.commit()
    
    return redirect(url_for('players'))

@app.route('/players/<int:player_id>/toggle-status', methods=['POST'])
@login_required
def toggle_player_status(player_id):
    with get_db() as conn:
        player = conn.execute('SELECT status FROM players WHERE id = ?', (player_id,)).fetchone()
        if player:
            new_status = 'retired' if player['status'] == 'active' else 'active'
            conn.execute('UPDATE players SET status = ? WHERE id = ?', (new_status, player_id))
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
        # Only active players can be added to a new or edited formation.
        players_list = conn.execute('''
            SELECT * FROM players
            WHERE status = 'active'
            ORDER BY name
        ''').fetchall()

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
        if match_id and conn.execute('SELECT id FROM matches WHERE id = ?', (match_id,)).fetchone() is None:
            return jsonify({'success': False, 'error': 'Match not found.'}), 404
        if formation_id:
            formation = conn.execute('SELECT private_team FROM formations WHERE id = ?', (formation_id,)).fetchone()
            if formation is None:
                return jsonify({'success': False, 'error': 'Formation not found.'}), 404
            private_team = formation['private_team'] or data.get('private_team') is True
            conn.execute('UPDATE formations SET name = ?, data = ?, private_team = ? WHERE id = ?',
                        (name, formation_data, int(private_team), formation_id))
            saved_id = formation_id
        else:
            # Create new formation
            private_team = data.get('private_team') is True
            cursor = conn.execute('INSERT INTO formations (name, data, private_team) VALUES (?, ?, ?)',
                        (name, formation_data, int(private_team)))
            saved_id = cursor.lastrowid
        
        # Link to match if match_id provided
        if match_id:
            if data.get('private_team') is True:
                conn.execute('UPDATE matches SET formation_id = ?, team_published = 0 WHERE id = ?',
                             (saved_id, match_id))
            elif private_team:
                conn.execute('''
                    UPDATE matches SET
                        team_published = CASE WHEN formation_id IS ? THEN team_published ELSE 0 END,
                        formation_id = ?
                    WHERE id = ?
                ''', (saved_id, saved_id, match_id))
            else:
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
            SELECT f.*, m.id as match_id, m.opponent, m.match_date, m.location,
                   mr.goals_json, mr.opponent_goals, mr.motm_player_id
            FROM formations f
            LEFT JOIN matches m ON m.formation_id = f.id
            LEFT JOIN match_results mr ON mr.match_id = m.id
            WHERE f.id = ?
        ''', (formation_id,)).fetchone()

    if not row:
        return redirect(url_for('formations'))

    formations = _json.loads(row['data']).get('formations', [])
    return render_live_match(row, formation_id, row['name'], formations)

@app.route('/formations/<int:formation_id>/matchday')
@login_required
def matchday_view(formation_id):
    return redirect(url_for('live_view', formation_id=formation_id))


def render_live_match(row, formation_id=None, formation_name=None, formations=None):
    import json
    formations = formations or []
    saved_goals = json.loads(row['goals_json'] or '[]')
    referenced_ids = {
        str(goal[key])
        for goal in saved_goals
        for key in ('scorer_id', 'assist_id')
        if goal.get(key)
    }
    if row['motm_player_id']:
        referenced_ids.add(str(row['motm_player_id']))

    squad_ids = {
        str(player['id'])
        for formation in formations
        for player in formation.get('players', []) + formation.get('subs', []) + formation.get('squad', [])
        if player.get('id') is not None
    }
    with get_db() as conn:
        all_players = conn.execute('SELECT id, name, position, status FROM players ORDER BY name').fetchall()
    squad = [
        dict(player)
        for player in all_players
        if str(player['id']) in referenced_ids
        or (str(player['id']) in squad_ids if formations else player['status'] == 'active')
    ]

    match_date_display = row['match_date'] or ''
    if match_date_display:
        try:
            match_date_display = datetime.strptime(match_date_display, '%Y-%m-%d').strftime('%a %d %b %Y')
        except ValueError:
            pass

    match_id = row['match_id']
    legacy_keys = ['matchDay_' + str(formation_id)] if formation_id else []
    if match_id:
        legacy_keys.append('matchDay_match-' + str(match_id))
    return render_template(
        'live.html',
        formation_id=formation_id,
        formation_name=formation_name or 'vs ' + row['opponent'],
        formations=formations,
        opponent=row['opponent'] or 'Opponent',
        match_date_display=match_date_display,
        location=row['location'] or '',
        result_config={
            'matchId': match_id,
            'opponent': row['opponent'] or 'Opponent',
            'squad': squad,
            'storageKey': 'matchResult_' + (str(match_id) if match_id else 'formation-' + str(formation_id)),
            'legacyKeys': legacy_keys,
            'savedState': {
                'goals': saved_goals,
                'opponentGoals': row['opponent_goals'] or 0,
                'motmPlayerId': str(row['motm_player_id']) if row['motm_player_id'] else None
            }
        },
        version=VERSION
    )

@app.route('/matches/<int:match_id>/result')
@app.route('/matches/<int:match_id>/live')
@login_required
def match_result_view(match_id):
    """Open the same live screen for fixtures with or without a team."""
    with get_db() as conn:
        row = conn.execute('''
            SELECT m.*, m.id as match_id, mr.goals_json, mr.opponent_goals, mr.motm_player_id
            FROM matches m
            LEFT JOIN match_results mr ON mr.match_id = m.id
            WHERE m.id = ?
        ''', (match_id,)).fetchone()

        if not row:
            return redirect(url_for('matches'))

        formation = conn.execute('SELECT * FROM formations WHERE id = ?', (row['formation_id'],)).fetchone()
    if formation:
        import json
        return render_live_match(
            row, formation['id'], formation['name'], json.loads(formation['data']).get('formations', [])
        )
    return render_live_match(row)

@app.route('/api/matches/<int:match_id>/result', methods=['GET', 'POST'])
@login_required
def api_match_result(match_id):
    import json

    with get_db() as conn:
        match = conn.execute('SELECT id FROM matches WHERE id = ?', (match_id,)).fetchone()
        if not match:
            return jsonify({'error': 'Match not found'}), 404

        if request.method == 'GET':
            result = conn.execute('SELECT * FROM match_results WHERE match_id = ?', (match_id,)).fetchone()
            if not result:
                return jsonify({'goals': [], 'opponentGoals': 0, 'motmPlayerId': None})
            return jsonify({
                'goals': json.loads(result['goals_json'] or '[]'),
                'opponentGoals': result['opponent_goals'],
                'motmPlayerId': str(result['motm_player_id']) if result['motm_player_id'] else None
            })

        data = request.get_json(silent=True) or {}
        raw_goals = data.get('goals', [])
        if not isinstance(raw_goals, list):
            return jsonify({'error': 'Goals must be a list'}), 400

        goals = []
        for goal in raw_goals:
            if not isinstance(goal, dict):
                return jsonify({'error': 'Each goal must be an object'}), 400

            scorer_id = goal.get('scorer_id')
            scorer_name = (goal.get('scorer') or '').strip()
            if not scorer_id or not scorer_name:
                return jsonify({'error': 'Each goal needs a scorer'}), 400
            if not conn.execute('SELECT id FROM players WHERE id = ?', (scorer_id,)).fetchone():
                return jsonify({'error': 'Goal scorer not found'}), 400

            assist_id = goal.get('assist_id')
            assist_name = (goal.get('assist') or '').strip() or None
            if assist_id and not conn.execute('SELECT id FROM players WHERE id = ?', (assist_id,)).fetchone():
                return jsonify({'error': 'Assist player not found'}), 400
            goals.append({
                'scorer_id': str(scorer_id),
                'scorer': scorer_name,
                'assist_id': str(assist_id) if assist_id else None,
                'assist': assist_name,
                'at': goal.get('at')
            })

        try:
            opponent_goals = int(data.get('opponentGoals', 0))
        except (TypeError, ValueError):
            return jsonify({'error': 'Opponent goals must be a number'}), 400
        opponent_goals = max(0, opponent_goals)

        motm_player_id = data.get('motmPlayerId') or None
        if motm_player_id:
            motm_player = conn.execute('SELECT id FROM players WHERE id = ?', (motm_player_id,)).fetchone()
            if not motm_player:
                return jsonify({'error': 'Man of the match player not found'}), 400

        conn.execute('''
            INSERT INTO match_results (match_id, goals_json, opponent_goals, motm_player_id, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(match_id) DO UPDATE SET
                goals_json = excluded.goals_json,
                opponent_goals = excluded.opponent_goals,
                motm_player_id = excluded.motm_player_id,
                updated_at = CURRENT_TIMESTAMP
        ''', (match_id, json.dumps(goals), opponent_goals, motm_player_id))
        conn.commit()

    return jsonify({'success': True})

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

def public_match_team(raw_match, all_players):
    """Resolve public team lists, including substitutes, from a saved formation."""
    import json
    match = dict(raw_match)
    playing_ids = set()
    if match['formation_data']:
        data = json.loads(match['formation_data'])
        for formation in data.get('formations', []):
            for player in formation.get('players', []) + formation.get('subs', []):
                playing_ids.add(str(player['id']))
    match['team_selected'] = bool(playing_ids)
    match['playing'] = [dict(p) for p in all_players if str(p['id']) in playing_ids]
    match['not_playing'] = [
        dict(p) for p in all_players
        if match['team_selected'] and str(p['id']) not in playing_ids
    ]
    return match


@app.route('/public/players/<int:player_id>')
def public_player(player_id):
    """Show upcoming non-playing dates without requiring a manager login."""
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db() as conn:
        player = conn.execute('SELECT id, name FROM players WHERE id = ?', (player_id,)).fetchone()
        if player is None:
            abort(404)
        upcoming = conn.execute('''
            SELECT m.match_date, m.opponent, m.location, f.data AS formation_data
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id AND m.team_published = 1
            WHERE m.match_date >= ?
            ORDER BY m.match_date, m.id
        ''', (today,)).fetchall()
    not_playing = []
    unselected = []
    for raw_match in upcoming:
        match = public_match_team(raw_match, [player])
        if not match['team_selected']:
            unselected.append(match)
        elif match['not_playing']:
            not_playing.append(match)
    return render_template(
        'public_player.html', player=player, not_playing=not_playing,
        unselected=unselected, version=VERSION
    )


@app.route('/public/next-match')
def public_next_match():
    """Public page showing the next upcoming match and all upcoming matches"""
    today = datetime.now().strftime('%Y-%m-%d')

    with get_db() as conn:
        # Find all upcoming matches (today or later)
        upcoming = conn.execute('''
            SELECT m.id, m.match_date, m.opponent, m.location,
                   f.id AS formation_id, f.data as formation_data, f.name as formation_name
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id AND m.team_published = 1
            WHERE m.match_date >= ?
            ORDER BY m.match_date ASC
        ''', (today,)).fetchall()

        # Get all players
        all_players = conn.execute('SELECT * FROM players ORDER BY name').fetchall()

    if not upcoming:
        return render_template('public_next_match.html', match=None, upcoming_matches=[], players=all_players, version=VERSION)

    all_upcoming = [public_match_team(m, all_players) for m in upcoming]
    next_match = all_upcoming[0]
    future_matches = all_upcoming[1:]

    return render_template('public_next_match.html', match=next_match, upcoming_matches=future_matches, players=all_players, version=VERSION)

@app.route('/public/overview')
def public_overview():
    """Public page showing all matches overview"""
    
    with get_db() as conn:
        # Get all matches with formations
        matches_list = conn.execute('''
            SELECT m.*, f.data as formation_data
            FROM matches m
            LEFT JOIN formations f ON m.formation_id = f.id
            WHERE m.formation_id IS NOT NULL AND m.team_published = 1
            ORDER BY m.match_date
        ''').fetchall()
        
        # Get all players
        all_players = conn.execute('SELECT * FROM players ORDER BY name').fetchall()
    
    # Process each match
    matches_with_teams = []
    for match in matches_list:
        match_dict = public_match_team(match, all_players)
        
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
                         players=all_players,
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
    """Open the next fixture, even when its team has not been selected."""
    today = datetime.now().strftime('%Y-%m-%d')
    with get_db() as conn:
        next_match = conn.execute('''
            SELECT * FROM matches
            WHERE match_date >= ?
            ORDER BY match_date ASC
            LIMIT 1
        ''', (today,)).fetchone()
    if next_match:
        return redirect(url_for('match_result_view', match_id=next_match['id']))
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
        formation = conn.execute('SELECT private_team FROM formations WHERE id = ?', (formation_id,)).fetchone()
        if formation is None:
            return jsonify({'success': False, 'error': 'Formation not found.'}), 404
        if conn.execute('SELECT id FROM matches WHERE id = ?', (match_id,)).fetchone() is None:
            return jsonify({'success': False, 'error': 'Match not found.'}), 404
        if formation['private_team']:
            conn.execute('UPDATE matches SET formation_id = ?, team_published = 0 WHERE id = ?',
                         (formation_id, match_id))
        else:
            conn.execute('UPDATE matches SET formation_id = ? WHERE id = ?', (formation_id, match_id))
        conn.commit()
    return jsonify({'success': True})

@app.route('/matches/<int:match_id>/publication', methods=['POST'])
@login_required
def set_team_publication(match_id):
    publication = request.form.get('published')
    if publication not in ('0', '1'):
        abort(400)
    with get_db() as conn:
        match = conn.execute('SELECT formation_id FROM matches WHERE id = ?', (match_id,)).fetchone()
        if match is None:
            abort(404)
        if not match['formation_id']:
            abort(400, description='Save a team before publishing it.')
        conn.execute('UPDATE matches SET team_published = ? WHERE id = ?', (int(publication), match_id))
        conn.commit()
    return redirect(url_for('matches'))

@app.route('/team-generator')
@login_required
def team_generator():
    with get_db() as conn:
        players_list = conn.execute('''
            SELECT * FROM players
            WHERE status = 'active'
            ORDER BY name
        ''').fetchall()
        # Get matches without formations
        matches_list = conn.execute('''
            SELECT id, match_date, opponent, location 
            FROM matches 
            WHERE formation_id IS NULL 
            ORDER BY match_date
        ''').fetchall()
    
    players = [dict(p) for p in players_list]
    matches = [dict(m) for m in matches_list]
    return render_template(
        'team_generator.html',
        players=players,
        matches=matches,
        selected_match_ids=[match['id'] for match in matches[:20]],
        invite_all_match_ids=[],
        unavailable_by_match={},
        team_size=12,
        num_games=len(matches) if matches else 4,
        version=VERSION
    )

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

def availability_export_context():
    with get_db() as conn:
        players = [dict(player) for player in conn.execute(
            "SELECT id, name, position FROM players WHERE status = 'active' ORDER BY name, id"
        ).fetchall()]
        matches = [dict(match) for match in conn.execute('''
            SELECT id, match_date, opponent, location FROM matches
            WHERE formation_id IS NULL ORDER BY match_date, id
        ''').fetchall()]
    return players, matches


@app.route('/team-generator/import-availability', methods=['POST'])
@login_required
def import_player_availability():
    import csv
    from io import StringIO

    players, matches = availability_export_context()
    active_ids = {str(player['id']) for player in players}
    available_ids = {str(match['id']) for match in matches}
    selected_ids = set(request.form.getlist('match_ids'))
    current_unavailable = {
        str(match['id']): request.form.getlist(f"unavailable_for_{match['id']}")
        for match in matches
    }

    def import_error(message):
        return render_template(
            'team_generator.html', error=message, players=players, matches=matches,
            selected_match_ids=[match['id'] for match in matches if str(match['id']) in selected_ids],
            unavailable_by_match=current_unavailable,
            invite_all_match_ids=request.form.getlist('invite_all_for'),
            team_size=request.form.get('team_size', 12), num_games=len(selected_ids),
            version=VERSION
        ), 400

    upload = request.files.get('availability_file')
    if not upload or not upload.filename:
        return import_error('Choose an exported availability CSV to import.')
    try:
        contents = upload.stream.read(2 * 1024 * 1024 + 1)
    finally:
        upload.close()
    if len(contents) > 2 * 1024 * 1024:
        return import_error('The availability CSV must be 2 MB or smaller.')
    imported = {}
    try:
        reader = csv.DictReader(StringIO(contents.decode('utf-8-sig'), newline=''), strict=True)
        required = {'Fixture ID', 'Player ID', 'Availability'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            return import_error('Use an exported availability CSV with Fixture ID, Player ID and Availability columns.')
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            return import_error('The CSV contains duplicate column headings.')
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                return import_error(f'CSV line {reader.line_num} has missing or extra columns.')
            fixture_id = row['Fixture ID'].strip()
            player_id = row['Player ID'].strip()
            status = row['Availability'].strip().lower()
            if fixture_id not in available_ids:
                return import_error(f'CSV line {reader.line_num}: fixture {fixture_id} is no longer available for planning.')
            if player_id not in active_ids:
                return import_error(f'CSV line {reader.line_num}: player {player_id} is missing or no longer active.')
            if status not in ('available', 'unavailable'):
                return import_error(f'CSV line {reader.line_num}: Availability must be Available or Unavailable.')
            fixture = imported.setdefault(fixture_id, {})
            if player_id in fixture:
                return import_error(f'CSV line {reader.line_num}: duplicate player {player_id} for fixture {fixture_id}.')
            fixture[player_id] = status
    except (UnicodeDecodeError, csv.Error):
        return import_error('The file is not a valid UTF-8 CSV. Save it as CSV UTF-8 and try again.')
    if not imported:
        return import_error('The CSV contains no player availability rows.')
    if any(set(fixture) != active_ids for fixture in imported.values()):
        return import_error('Each imported fixture must include every active player. Export a fresh CSV if the squad has changed.')

    return render_template(
        'team_generator.html', players=players, matches=matches,
        selected_match_ids=[match['id'] for match in matches if str(match['id']) in imported],
        unavailable_by_match={
            fixture_id: [player_id for player_id, status in fixture.items() if status == 'unavailable']
            for fixture_id, fixture in imported.items()
        },
        invite_all_match_ids=request.form.getlist('invite_all_for'),
        team_size=request.form.get('team_size', 12), num_games=len(imported),
        success=f'Imported availability for {len(imported)} fixture(s). Review the ticks before generating teams.',
        version=VERSION
    )


@app.route('/team-generator/export-availability', methods=['POST'])
@login_required
def export_player_availability():
    import csv
    from io import StringIO

    players, matches = availability_export_context()

    submitted_ids = set(request.form.getlist('match_ids'))
    available_ids = {str(match['id']) for match in matches}
    active_ids = {str(player['id']) for player in players}
    selected_matches = [match for match in matches if str(match['id']) in submitted_ids]
    unavailable_by_match = {
        str(match['id']): request.form.getlist(f"unavailable_for_{match['id']}")
        for match in selected_matches
    }
    error = None
    if not submitted_ids:
        error = 'Select at least one fixture to export availability.'
    elif submitted_ids - available_ids:
        error = 'One or more selected fixtures are no longer available. Refresh the page and try again.'
    elif not players:
        error = 'Add active players before exporting availability.'
    elif any(set(ids) - active_ids for ids in unavailable_by_match.values()):
        error = 'One or more players are no longer active. Refresh the page and review availability.'
    if error:
        return render_template(
            'team_generator.html', error=error, players=players, matches=matches,
            selected_match_ids=[match['id'] for match in selected_matches],
            unavailable_by_match=unavailable_by_match,
            invite_all_match_ids=request.form.getlist('invite_all_for'),
            team_size=request.form.get('team_size', 12),
            num_games=len(selected_matches), version=VERSION
        ), 400

    def spreadsheet_text(value):
        text = str(value or '')
        # CSV quoting does not prevent spreadsheet formula execution.
        if text.lstrip().startswith(('=', '+', '-', '@')) or text.startswith(('\t', '\r', '\n')):
            return "'" + text
        return text

    output = StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Fixture ID', 'Date', 'Opponent', 'Location',
                     'Player ID', 'Player', 'Position', 'Availability'])
    for match in selected_matches:
        unavailable_ids = set(unavailable_by_match[str(match['id'])])
        for player in players:
            writer.writerow([
                match['id'], datetime.strptime(match['match_date'], '%Y-%m-%d').strftime('%d/%m/%Y'),
                spreadsheet_text(match['opponent']), spreadsheet_text(match['location']),
                player['id'], spreadsheet_text(player['name']), spreadsheet_text(player['position']),
                'Unavailable' if str(player['id']) in unavailable_ids else 'Available'
            ])

    response = app.response_class(
        '\ufeff' + output.getvalue(), mimetype='text/csv'
    )
    response.headers['Content-Disposition'] = (
        'attachment; filename="player-availability-' + datetime.now().strftime('%Y-%m-%d') + '.csv"'
    )
    response.headers['Cache-Control'] = 'no-store'
    return response

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
    import random
    from collections import defaultdict
    
    try:
        requested_num_games = int(request.form.get('num_games', 4))
        team_size = int(request.form.get('team_size', 12))
    except (TypeError, ValueError):
        return render_template('team_generator.html', error='Enter a valid number of games and team size.', version=VERSION)

    submitted_match_ids = request.form.getlist('match_ids')
    requested_invite_all_ids = {str(match_id) for match_id in request.form.getlist('invite_all_for')}
    
    # Retired players are intentionally excluded from newly generated teams.
    with get_db() as conn:
        players_list = conn.execute('''
            SELECT * FROM players
            WHERE status = 'active'
            ORDER BY name
        ''').fetchall()
        matches_list = conn.execute('''
            SELECT id, match_date, opponent, location
            FROM matches
            WHERE formation_id IS NULL
            ORDER BY match_date
        ''').fetchall()

    players = [dict(p) for p in players_list]
    matches = [dict(m) for m in matches_list]
    available_match_ids = {str(match['id']) for match in matches}
    active_player_ids = {str(player['id']) for player in players}
    unavailable_by_match = {
        str(match['id']): [
            player_id for player_id in request.form.getlist(f"unavailable_for_{match['id']}")
            if player_id in active_player_ids
        ]
        for match in matches
    }
    selected_matches = [match for match in matches if str(match['id']) in submitted_match_ids]
    selected_match_ids = [match['id'] for match in selected_matches]
    invite_all_match_ids = requested_invite_all_ids.intersection({str(match_id) for match_id in selected_match_ids})

    def render_generator_error(message):
        return render_template(
            'team_generator.html',
            error=message,
            players=players,
            matches=matches,
            selected_match_ids=selected_match_ids,
            invite_all_match_ids=list(invite_all_match_ids),
            unavailable_by_match=unavailable_by_match,
            team_size=team_size,
            num_games=requested_num_games,
            goalkeeper_percentages={str(p['id']): request.form.get(f"goalkeeper_percentage_{p['id']}", '')
                                    for p in players if p['position'] == 'GK'},
            version=VERSION
        )

    if submitted_match_ids:
        invalid_match_ids = set(submitted_match_ids) - available_match_ids
        if invalid_match_ids:
            return render_generator_error('One or more selected games are no longer available. Refresh the page and try again.')
        if not selected_matches:
            return render_generator_error('Select at least one game to generate teams for.')
        if len(selected_matches) > 20:
            return render_generator_error('Select 20 games or fewer at a time.')
        num_games = len(selected_matches)
    else:
        num_games = requested_num_games

    if num_games < 1 or num_games > 20:
        return render_generator_error('Choose between 1 and 20 games.')
    if team_size < 9 or team_size > 15:
        return render_generator_error('Team size must be between 9 and 15 players.')

    # Randomize player order at start to ensure different results each time.
    random.shuffle(players)

    goalkeepers = [p for p in players if p['position'] == 'GK']
    if not goalkeepers:
        return render_generator_error('No goalkeepers found! Please add at least one player with position "GK".')

    # Validate each fixture before generating so exclusions cannot produce a
    # silently undersized team or a game without a goalkeeper.
    game_plans = []
    for game in range(num_games):
        game_match = selected_matches[game] if selected_matches else None
        match_key = str(game_match['id']) if game_match else None
        unavailable_ids = set(unavailable_by_match.get(match_key, [])) if match_key else set()
        eligible_players = [p for p in players if str(p['id']) not in unavailable_ids]
        invite_all_players = bool(game_match and match_key in invite_all_match_ids)
        game_team_size = len(eligible_players) if invite_all_players else team_size
        game_label = (
            f"{game_match['match_date']} vs {game_match['opponent']}"
            if game_match else f"Game {game + 1}"
        )

        if game_team_size < 9:
            return render_generator_error(
                f'{game_label} has only {len(eligible_players)} available players; at least 9 are needed.'
            )
        if len(eligible_players) < game_team_size:
            return render_generator_error(
                f'{game_label} has only {len(eligible_players)} available players; '
                f'{game_team_size} are needed after exclusions.'
            )

        eligible_gks = [p for p in eligible_players if p['position'] == 'GK']
        if not eligible_gks:
            return render_generator_error(f'{game_label} has no available goalkeeper.')

        game_plans.append({
            'match': game_match,
            'unavailable_ids': unavailable_ids,
            'eligible_players': eligible_players,
            'eligible_gks': eligible_gks,
            'invite_all_players': invite_all_players,
            'team_size': game_team_size,
        })

    keeper_percentages = {}
    try:
        for keeper in goalkeepers:
            value = request.form.get(f"goalkeeper_percentage_{keeper['id']}", '').strip()
            keeper_percentages[keeper['id']] = int(value) if value else None
    except ValueError:
        return render_generator_error('Enter whole-number goalkeeper percentages between 0 and 100.')
    supplied = [value for value in keeper_percentages.values() if value is not None]
    if supplied and (len(supplied) != len(goalkeepers) or
                     any(value < 0 or value > 100 for value in supplied) or sum(supplied) != 100):
        return render_generator_error('Set every goalkeeper percentage between 0 and 100, totalling 100%, or leave all blank for equal rotation.')
    normal_games = [index for index, plan in enumerate(game_plans) if not plan['invite_all_players']]
    weights = {p['id']: keeper_percentages[p['id']] if supplied else 100 / len(goalkeepers)
               for p in goalkeepers}
    exact_targets = {pid: len(normal_games) * weight / 100 for pid, weight in weights.items()}
    keeper_targets = {pid: int(target) for pid, target in exact_targets.items()}
    remainder = len(normal_games) - sum(keeper_targets.values())
    ranked_ids = sorted(exact_targets, key=lambda pid: exact_targets[pid] - keeper_targets[pid], reverse=True)
    for pid in ranked_ids[:remainder]:
        keeper_targets[pid] += 1

    # Match quota slots to eligible fixtures, reassigning earlier choices when needed.
    assigned_keepers = {}
    def assign_keeper(keeper, visited):
        for index in normal_games:
            if index in visited or keeper not in game_plans[index]['eligible_gks']:
                continue
            visited.add(index)
            previous = assigned_keepers.get(index)
            if previous is None or assign_keeper(previous, visited):
                assigned_keepers[index] = keeper
                return True
        return False

    for keeper in goalkeepers:
        for _ in range(keeper_targets[keeper['id']]):
            if not assign_keeper(keeper, set()):
                return render_generator_error(
                    'Goalkeeper targets cannot cover every selected fixture with the current availability. '
                    'Adjust percentages or availability and try again.'
                )

    # Weight each player's selection by the games they can actually attend.
    # This keeps scarce availability from being crowded out by fully available players.
    eligible_game_counts = defaultdict(int)
    total_team_slots = 0
    for plan in game_plans:
        total_team_slots += plan['team_size']
        for player in plan['eligible_players']:
            eligible_game_counts[player['id']] += 1
    average_games = total_team_slots / len(players) if players else 0

    def fairness_key(player, player_game_count):
        eligible_games = eligible_game_counts[player['id']]
        target_games = min(eligible_games, average_games) if average_games else eligible_games
        normalized_count = player_game_count[player['id']] / target_games if target_games else float('inf')
        return (normalized_count, player_game_count[player['id']], eligible_games, random.random())

    teams = []
    player_game_count = defaultdict(int)
    keeper_game_count = defaultdict(int)
    # Reserve all mandatory selections before rotating the remaining places.
    # Otherwise a keeper can gain extra games before their later in-goal assignments.
    for game_index, plan in enumerate(game_plans):
        if plan['invite_all_players']:
            for player in plan['eligible_players']:
                player_game_count[player['id']] += 1
        else:
            keeper = assigned_keepers[game_index]
            player_game_count[keeper['id']] += 1

    outfield_teams = {index: [] for index in normal_games}

    def assign_outfield(player, visited):
        for index in normal_games:
            plan = game_plans[index]
            roster = outfield_teams[index]
            if (index in visited or player not in plan['eligible_players'] or
                    player['id'] == assigned_keepers[index]['id'] or player in roster):
                continue
            visited.add(index)
            if len(roster) < plan['team_size'] - 1:
                roster.append(player)
                return True
            for previous in roster[:]:
                if assign_outfield(previous, visited):
                    roster.remove(previous)
                    roster.append(player)
                    return True
        return False

    # Fill globally rather than fixture by fixture so later mandatory keeper
    # assignments cannot leave a keeper with more rest games than their peers.
    optional_slots = sum(game_plans[index]['team_size'] - 1 for index in normal_games)
    for _ in range(optional_slots):
        for player in sorted(players, key=lambda p: fairness_key(p, player_game_count)):
            if assign_outfield(player, set()):
                player_game_count[player['id']] += 1
                break
        else:
            return render_generator_error('Unable to fill every team with the current availability. Review availability and try again.')

    for game_index, plan in enumerate(game_plans):
        eligible_players = plan['eligible_players']
        if plan['invite_all_players']:
            full_team = eligible_players[:]
            gk_in_starters = random.choice(plan['eligible_gks'])
        else:
            gk_in_starters = assigned_keepers[game_index]
            full_team = [gk_in_starters] + outfield_teams[game_index]

        random.shuffle(full_team)

        keeper_game_count[gk_in_starters['id']] += 1
        starters = [gk_in_starters]
        remaining = [
            dict(player, position='Outfield') if player['position'] == 'GK' else dict(player)
            for player in full_team if player['id'] != gk_in_starters['id']
        ]
        starters.extend(remaining[:8])
        subs = remaining[8:]

        team_player_ids = {player['id'] for player in full_team}
        unavailable_ids = plan['unavailable_ids']
        not_playing = [
            player for player in eligible_players
            if player['id'] not in team_player_ids
        ]
        unavailable = [
            player for player in players
            if str(player['id']) in unavailable_ids
        ]
        game_match = plan['match']

        teams.append({
            'starters': starters,
            'subs': subs,
            'not_playing': not_playing,
            'unavailable': unavailable,
            'match_id': game_match['id'] if game_match else None,
            'match_label': (
                f"{game_match['match_date']} - vs {game_match['opponent']}"
                if game_match else None
            ),
            'invite_all_players': plan['invite_all_players']
        })
    
    # Count missed games only where a player was available to attend.
    max_games_missed = max(
        (eligible_game_counts[player['id']] - player_game_count[player['id']]
         for player in players),
        default=0
    )
    unavailable_count = sum(len(plan['unavailable_ids']) for plan in game_plans)

    stats = {
        'total_players': len(players),
        'num_games': num_games,
        'team_size': team_size,
        'max_games_missed': max_games_missed,
        'unavailable_count': unavailable_count,
        'invite_all_count': len(invite_all_match_ids)
    }
    stats['goalkeepers'] = [
        {'name': keeper['name'], 'target': round(weights[keeper['id']], 2),
         'games': player_game_count[keeper['id']], 'in_goal': keeper_game_count[keeper['id']],
         'resting': eligible_game_counts[keeper['id']] - player_game_count[keeper['id']],
         'total': num_games}
        for keeper in goalkeepers
    ]
    
    return render_template('team_generator.html', 
                         teams=teams, 
                         stats=stats,
                         players=players,
                         matches=matches,
                         selected_match_ids=selected_match_ids,
                         invite_all_match_ids=list(invite_all_match_ids),
                         unavailable_by_match=unavailable_by_match,
                         team_size=team_size,
                         num_games=num_games,
                         goalkeeper_percentages={str(pid): value if value is not None else ''
                                                 for pid, value in keeper_percentages.items()},
                         version=VERSION)

if __name__ == '__main__':
    init_db()
    load_password_from_db()
    port = int(os.environ.get('PORT', 8081))
    app.run(host='0.0.0.0', port=port, debug=True)
