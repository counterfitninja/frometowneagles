import json
import re
import unittest
from datetime import timedelta

import test_public_players as fixtures

application = fixtures.application


class ClearSquadsTests(unittest.TestCase):
    setUp = fixtures.PublicPlayerTests.setUp
    tearDown = fixtures.PublicPlayerTests.tearDown
    fixture = fixtures.PublicPlayerTests.fixture

    def login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def token(self, path='/matches'):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Clear all squads', html)
        self.assertIn('return confirm(', html)
        return re.search(r'name="csrf_token" value="([^"]+)"', html)[1]

    def test_clears_all_upcoming_squads_and_preserves_other_data(self):
        self.login()
        team = [{'players': [{'id': 1}], 'subs': [{'id': 2}]}]
        self.fixture('Past', -1, team)
        self.fixture('Today shared', 0, formation_id=1)
        self.fixture('Future draft', 1, team)
        self.fixture('Future published', 2, team)
        self.fixture('Next season', 400, team)
        self.fixture('No squad', 3)
        with application.get_db() as conn:
            conn.execute('UPDATE matches SET team_published=0 WHERE id=3')
            conn.execute('UPDATE formations SET private_team=1 WHERE id=2')
            conn.execute('INSERT INTO formations (name, data) VALUES (?, ?)',
                         ('Unlinked saved formation', json.dumps({'formations': team})))
            conn.execute('INSERT INTO match_results (match_id, opponent_goals) VALUES (3, 2)')
            conn.execute('INSERT INTO player_unavailability (player_id, unavailable_date) VALUES (1, ?)',
                         ((self.today + timedelta(days=1)).isoformat(),))
            conn.execute('''
                INSERT INTO player_availability_confirmations (player_id, season_start, confirmed_at)
                VALUES (1, ?, ?)
            ''', (application.current_season_bounds()[1], self.today.isoformat()))
            conn.commit()
            before_matches = [dict(row) for row in conn.execute('SELECT * FROM matches ORDER BY id')]
            before_formations = [dict(row) for row in conn.execute('SELECT * FROM formations ORDER BY id')]
            preserved_tables = ('match_results', 'player_unavailability',
                                'player_availability_confirmations', 'players', 'settings')
            before = {table: [dict(row) for row in conn.execute(f'SELECT * FROM {table}')]
                      for table in preserved_tables}

        response = self.client.post('/matches/clear-squads', data={'csrf_token': self.token()},
                                    follow_redirects=True)
        self.assertIn('Cleared squads for 4 upcoming game(s).', response.get_data(as_text=True))
        with application.get_db() as conn:
            matches = [dict(row) for row in conn.execute('SELECT * FROM matches ORDER BY id')]
            self.assertEqual(len(matches), 6)
            for index, match in enumerate(matches):
                expected = dict(before_matches[index])
                if 1 <= index <= 4:
                    expected.update(formation_id=None, team_published=0)
                self.assertEqual(match, expected)
            self.assertEqual([dict(row) for row in conn.execute('SELECT * FROM formations ORDER BY id')],
                             [before_formations[0], before_formations[-1]])
            for table in preserved_tables:
                self.assertEqual([dict(row) for row in conn.execute(f'SELECT * FROM {table}')],
                                 before[table])
        html = self.client.get('/public/players/1').get_data(as_text=True)
        self.assertIn('Team not selected', html)
        self.assertIn('You have no upcoming non-playing dates in the selected teams.', html)
        summary = self.client.get('/players').get_data(as_text=True)
        self.assertIn('saved squad (0)', summary)

    def test_requires_login_post_and_valid_token(self):
        self.fixture('Future', 1, [{'players': [{'id': 1}]}])
        self.assertEqual(self.client.post('/matches/clear-squads').status_code, 302)
        self.login()
        self.assertEqual(self.client.get('/matches/clear-squads').status_code, 405)
        token = self.token()
        for data in ({}, {'csrf_token': 'invalid'}):
            self.assertEqual(self.client.post('/matches/clear-squads', data=data).status_code, 400)
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT formation_id FROM matches').fetchone()[0], 1)
        self.assertEqual(self.client.post('/matches/clear-squads',
                                         data={'csrf_token': token}).status_code, 302)

    def test_return_pages_and_empty_repeat(self):
        self.login()
        for path, values in (
                ('/matches?show_past=true', {'show_past': 'true'}),
                ('/team-generator', {'return_to': 'team_generator'}),
                ('/team-generator?regenerate=1', {'return_to': 'team_generator', 'regenerate': '1'})):
            with self.subTest(path=path):
                response = self.client.post('/matches/clear-squads',
                                            data={'csrf_token': self.token(path), **values})
                self.assertEqual(response.status_code, 302)
                for key, value in values.items():
                    if key != 'return_to':
                        self.assertIn(f'{key}={value}', response.location)
                expected_path = '/team-generator' if values.get('return_to') else '/matches'
                self.assertTrue(response.location.startswith(expected_path))
                html = self.client.get(response.location).get_data(as_text=True)
                self.assertIn('No saved squads to clear for upcoming games.', html)


if __name__ == '__main__':
    unittest.main()
