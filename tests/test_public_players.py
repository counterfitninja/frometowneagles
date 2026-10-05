import gc
import json
import os
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

with tempfile.TemporaryDirectory() as import_directory:
    with patch.dict(os.environ, {'DATABASE_PATH': str(Path(import_directory) / 'import.db')}):
        import app as application
    gc.collect()


class PublicPlayerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = str(Path(self.directory.name) / 'test.db')
        self.connections = []
        original_get_db = application.get_db

        def tracked_get_db():
            connection = original_get_db()
            self.connections.append(connection)
            return connection

        self.database_patch = patch.object(application, 'get_db', side_effect=tracked_get_db)
        self.database_patch.start()
        application.init_db()
        self.client = application.app.test_client()
        self.today = datetime.now().date()
        with application.get_db() as conn:
            conn.executemany(
                'INSERT INTO players (id, name, position, rating) VALUES (?, ?, ?, ?)',
                [(1, 'Alex', 'GK', 5), (2, 'Alex', 'DEF', 4),
                 (3, 'Sam <script>', 'MID', 3)]
            )
            conn.commit()

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.database_patch.stop()
        application.DATABASE = self.original_database
        self.directory.cleanup()

    def fixture(self, opponent, days, formations=None, formation_id=None):
        with application.get_db() as conn:
            if formations is not None:
                cursor = conn.execute(
                    'INSERT INTO formations (name, data) VALUES (?, ?)',
                    (opponent, json.dumps({'formations': formations}))
                )
                formation_id = cursor.lastrowid
            conn.execute(
                'INSERT INTO matches (match_date, opponent, location, formation_id) VALUES (?, ?, ?, ?)',
                ((self.today + timedelta(days=days)).isoformat(), opponent, 'Home', formation_id)
            )
            conn.commit()

    def page(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_only_upcoming_non_playing_dates_are_listed(self):
        self.fixture('Past rest', -1, [{'players': [{'id': 2}]}])
        self.fixture('Today rest', 0, [{'players': [{'id': 2}]}])
        self.fixture('Future rest', 4, [{'players': [{'id': '2'}]}])
        self.fixture('Starting', 1, [{'players': [{'id': '1'}]}])
        self.fixture('Substitute', 2, [{'players': [{'id': 2}], 'subs': [{'id': 1}]}])
        self.fixture('Second team', 3, [{'players': []}, {'players': [{'id': 1}]}])

        html = self.page('/public/players/1')
        self.assertIn('Today rest', html)
        self.assertIn('Future rest', html)
        for opponent in ('Past rest', 'Starting', 'Substitute', 'Second team'):
            self.assertNotIn(opponent, html)
        self.assertLess(html.index('Today rest'), html.index('Future rest'))
        self.assertIn((self.today + timedelta(days=4)).strftime('%d/%m/%Y'), html)
        self.assertIn('Home', html)

    def test_unselected_fixtures_are_separate(self):
        self.fixture('Awaiting selection', 1)
        self.fixture('Missing formation', 2, formation_id=999)
        self.fixture('Empty team', 2, [{'players': [], 'subs': []}])
        self.fixture('Confirmed rest', 3, [{'players': [{'id': 2}]}])
        html = self.page('/public/players/1')
        confirmed, pending = html.split('<h2 id="unselected-heading">')
        self.assertIn('Confirmed rest', confirmed)
        self.assertNotIn('Awaiting selection', confirmed)
        self.assertNotIn('Missing formation', confirmed)
        self.assertNotIn('Empty team', confirmed)
        self.assertIn('Awaiting selection', pending)
        self.assertIn('Missing formation', pending)
        self.assertIn('Empty team', pending)

    def test_empty_teams_do_not_mark_everyone_as_not_playing(self):
        self.fixture('Empty team', 1, [{'players': [], 'subs': []}])
        for path in ('/public/next-match', '/public/overview'):
            html = self.page(path)
            self.assertIn('No team selected for this match', html)
            self.assertNotIn('class="player-chip not-playing"', html)

    def test_empty_schedule_and_missing_player(self):
        self.assertIn('no upcoming non-playing dates', self.page('/public/players/1'))
        self.assertEqual(self.client.get('/public/players/999').status_code, 404)
        self.assertEqual(self.client.get('/players').status_code, 302)

    def test_names_are_escaped(self):
        html = self.page('/public/players/3')
        self.assertIn('Sam &lt;script&gt;', html)
        self.assertNotIn('Sam <script>', html)

    def test_public_pages_link_names_even_without_matches(self):
        for path in ('/public/next-match', '/public/overview'):
            html = self.page(path)
            for player_id in (1, 2, 3):
                self.assertIn(f'href="/public/players/{player_id}"', html)
            self.assertIn('When am I not playing?', html)
            self.assertIn('<details class="card player-picker" open>', html)

    def test_playing_and_non_playing_chips_link_to_player(self):
        self.fixture('First fixture', 0, [{'players': [{'id': 1}]}])
        self.fixture('Next fixture', 1, [{'players': [{'id': 2}]}])
        for path in ('/public/next-match', '/public/overview'):
            html = self.page(path)
            self.assertIn('class="player-chip" href="/public/players/1"', html)
            self.assertIn('class="player-chip not-playing" href="/public/players/2"', html)
        html = self.page('/public/next-match')
        self.assertIn('class="upcoming-not-playing-chip" href="/public/players/1"', html)


if __name__ == '__main__':
    unittest.main()
