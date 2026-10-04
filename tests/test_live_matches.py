import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from test_public_players import application


class LiveMatchTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.original_database = application.DATABASE
        application.DATABASE = str(Path(self.directory.name) / 'live.db')
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
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        self.today = datetime.now().date()
        with application.get_db() as conn:
            conn.executemany(
                'INSERT INTO players (id, name, position, status) VALUES (?, ?, ?, ?)',
                [(1, 'Alex', 'GK', 'active'), (2, 'Alex', 'DEF', 'active'),
                 (3, 'Sam </script>', 'MID', 'active'), (4, 'Retired', 'MID', 'retired'),
                 (5, 'Historic scorer', 'DEF', 'retired')]
            )
            conn.commit()

    def tearDown(self):
        for connection in self.connections:
            connection.close()
        self.database_patch.stop()
        application.DATABASE = self.original_database
        self.directory.cleanup()

    def fixture(self, days=0, formation_id=None):
        with application.get_db() as conn:
            cursor = conn.execute(
                'INSERT INTO matches (match_date, opponent, location, formation_id) VALUES (?, ?, ?, ?)',
                ((self.today + timedelta(days=days)).isoformat(), "Town's </script>", 'Home', formation_id)
            )
            conn.commit()
            return cursor.lastrowid

    def formation(self):
        with application.get_db() as conn:
            cursor = conn.execute(
                'INSERT INTO formations (name, data) VALUES (?, ?)',
                ('Teams', json.dumps({'formations': [
                    {'name': 'First half', 'players': [{'id': 1, 'name': 'Alex'}],
                     'subs': [{'id': 2, 'name': 'Alex'}]},
                    {'name': 'Second half', 'players': [{'id': 3, 'name': 'Sam </script>'}], 'subs': []}
                ]}))
            )
            conn.commit()
            return cursor.lastrowid

    def page(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def config(self, html):
        raw = re.search(r'<script id="resultConfig" type="application/json">(.*?)</script>', html, re.S)[1]
        self.assertNotIn('</script>', raw)
        return json.loads(raw)

    def test_live_combines_score_and_substitutions_for_all_teams(self):
        formation_id = self.formation()
        match_id = self.fixture(formation_id=formation_id)
        html = self.page(f'/matches/{match_id}/live')
        config = self.config(html)
        self.assertEqual(config['matchId'], match_id)
        self.assertEqual([player['id'] for player in config['squad']], [1, 2, 3])
        self.assertEqual(config['storageKey'], f'matchResult_{match_id}')
        self.assertEqual(config['legacyKeys'], [f'matchDay_{formation_id}', f'matchDay_match-{match_id}'])
        for control in ('goalButton', 'opponentGoalButton', 'subBtn', 'pitchEl', 'resultPicker', 'motmButton'):
            self.assertIn(f'id="{control}"', html)
        self.assertIn('First half', html)
        self.assertIn('Second half', html)
        self.assertNotIn('Sam </script>', html)

    def test_no_formation_still_has_live_results(self):
        match_id = self.fixture()
        html = self.page(f'/matches/{match_id}/live')
        self.assertIn('No team selected', html)
        self.assertIn('id="goalButton"', html)
        self.assertNotIn('id="pitchEl"', html)
        self.assertNotIn('id="subBtn"', html)
        self.assertEqual([p['id'] for p in self.config(html)['squad']], [1, 2, 3])
        self.assertEqual(self.config(self.page(f'/matches/{match_id}/result'))['matchId'], match_id)

    def test_legacy_matchday_redirects_to_live(self):
        formation_id = self.formation()
        self.fixture(formation_id=formation_id)
        response = self.client.get(f'/formations/{formation_id}/matchday')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, f'/formations/{formation_id}/live')
        self.assertIn('id="subBtn"', self.page(response.location))

    def test_next_match_does_not_skip_fixtures_without_teams(self):
        self.fixture(-1, self.formation())
        match_id = self.fixture(0)
        self.fixture(1, self.formation())
        response = self.client.get('/live')
        self.assertEqual(response.location, f'/matches/{match_id}/live')
        self.assertEqual(self.client.get(response.location).status_code, 200)

    def test_live_without_fixtures_returns_to_matches(self):
        self.assertEqual(self.client.get('/live').location, '/matches')
        self.assertEqual(self.client.get('/matches/999/live').location, '/matches')
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get('/matches/1/live').status_code, 302)

    def test_results_and_retired_referenced_players_survive_consolidation(self):
        formation_id = self.formation()
        match_id = self.fixture(formation_id=formation_id)
        goals = [{'scorer_id': '5', 'scorer': 'Historic scorer',
                  'assist_id': '2', 'assist': 'Alex', 'at': 42}]
        payload = {'goals': goals, 'opponentGoals': 2, 'motmPlayerId': '5'}
        response = self.client.post(f'/api/matches/{match_id}/result', json=payload)
        self.assertEqual(response.status_code, 200)
        config = self.config(self.page(f'/matches/{match_id}/live'))
        self.assertEqual(config['savedState'], payload)
        self.assertIn(5, [player['id'] for player in config['squad']])
        self.assertNotIn(4, [player['id'] for player in config['squad']])
        self.assertIn('Historic scorer', self.page('/stats'))
        unselected_id = self.fixture(1)
        self.client.post(f'/api/matches/{unselected_id}/result', json=payload)
        self.assertIn(5, [p['id'] for p in self.config(self.page(f'/matches/{unselected_id}/live'))['squad']])

    def test_fixture_url_uses_exact_match_when_formation_is_shared(self):
        formation_id = self.formation()
        self.fixture(formation_id=formation_id)
        second_id = self.fixture(1, formation_id)
        config = self.config(self.page(f'/matches/{second_id}/live'))
        self.assertEqual(config['matchId'], second_id)

    def test_substituted_players_remain_available_after_saving_the_lineup(self):
        formation_id = self.formation()
        match_id = self.fixture(formation_id=formation_id)
        data = {'formations': [{
            'name': 'First half',
            'players': [{'id': 2, 'name': 'Alex'}],
            'subs': [],
            'squad': [{'id': 1, 'name': 'Alex'}, {'id': 2, 'name': 'Alex'}]
        }]}
        response = self.client.post('/formations/save', json={
            'id': formation_id, 'name': 'Teams', 'data': json.dumps(data)
        })
        self.assertEqual(response.status_code, 200)
        config = self.config(self.page(f'/matches/{match_id}/live'))
        self.assertEqual([player['id'] for player in config['squad']], [1, 2])

    def test_unlinked_formation_can_only_save_result_locally(self):
        formation_id = self.formation()
        config = self.config(self.page(f'/formations/{formation_id}/live'))
        self.assertIsNone(config['matchId'])
        self.assertEqual(config['storageKey'], f'matchResult_formation-{formation_id}')

    def test_offline_worker_can_control_the_live_pages(self):
        with self.client.get('/static/sw.js') as response:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['Service-Worker-Allowed'], '/')
        for asset in ('live-match.css?v=20261004', 'match-result.js?v=20261004',
                      'icon-192.svg', 'icon-512.svg'):
            with self.client.get('/static/' + asset) as response:
                self.assertEqual(response.status_code, 200)

    def test_primary_navigation_and_fixture_actions_are_reduced(self):
        match_id = self.fixture(formation_id=self.formation())
        html = self.page('/matches')
        nav = re.search(r'<nav .*?</nav>', html, re.S)[0]
        primary, secondary = nav.split('<details', 1)
        self.assertEqual(re.findall(r'href="([^"]+)"', primary), ['/', '/matches', '/players', '/live'])
        for link in ('/team-generator', '/formations', '/stats', '/settings', '/logout', '/gameday'):
            self.assertIn(f'href="{link}"', secondary)
        self.assertIn(f'href="/matches/{match_id}/live"', html)
        self.assertNotIn('⚽ Match Day', html)
        self.assertIn('View team sheet', html)
        self.assertIn('Share team', html)
        self.assertIn('Edit fixture', html)
        self.assertIn('Delete fixture', html)
        self.assertIn('<details class="bulk-upload-section"', html)
        self.assertNotIn('<details class="bulk-upload-section" open', html)


if __name__ == '__main__':
    unittest.main()
