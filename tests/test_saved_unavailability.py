import csv
from datetime import timedelta
from io import StringIO
import re
import unittest
from werkzeug.datastructures import MultiDict

import test_public_players as fixtures

application = fixtures.application


class SavedUnavailabilityTests(unittest.TestCase):
    setUp = fixtures.PublicPlayerTests.setUp
    tearDown = fixtures.PublicPlayerTests.tearDown

    def login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def fixture(self, days, opponent='Town', formation_id=None):
        with application.get_db() as conn:
            cursor = conn.execute(
                'INSERT INTO matches (match_date, opponent, location, formation_id) VALUES (?, ?, ?, ?)',
                ((self.today + timedelta(days=days)).isoformat(), opponent, 'Home', formation_id))
            conn.commit()
            return cursor.lastrowid

    def saved(self):
        with application.get_db() as conn:
            return [tuple(row) for row in conn.execute(
                'SELECT player_id, unavailable_date FROM player_unavailability ORDER BY unavailable_date, player_id')]

    def checked(self, html, element_id):
        tag = re.search(r'<input\b[^>]*\bid="' + re.escape(element_id) + r'"[^>]*>', html)[0]
        return bool(re.search(r'\bchecked\b', tag))

    def test_save_persists_by_date_and_prefills_generator(self):
        self.login()
        match_id = self.fixture(3)
        response = self.client.post('/team-generator/save-availability', data=MultiDict([
            ('match_ids', str(match_id)), (f'unavailable_for_{match_id}', '2'),
            (f'unavailable_for_{match_id}', '999')]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('Saved availability against players', response.get_data(as_text=True))
        date = (self.today + timedelta(days=3)).isoformat()
        self.assertEqual(self.saved(), [(2, date)])
        html = self.client.get('/team-generator').get_data(as_text=True)
        self.assertTrue(self.checked(html, f'unavailable-{match_id}-2'))
        self.assertFalse(self.checked(html, f'unavailable-{match_id}-1'))

        self.client.post('/team-generator/save-availability', data=MultiDict([('match_ids', str(match_id))]))
        self.assertEqual(self.saved(), [])

    def test_generate_saves_ticks_and_they_survive_squad_saved(self):
        self.login()
        match_id = self.fixture(1)
        self.client.post('/team-generator/generate', data=MultiDict([
            ('match_ids', str(match_id)), (f'unavailable_for_{match_id}', '3'), ('team_size', '9')]))
        date = (self.today + timedelta(days=1)).isoformat()
        self.assertEqual(self.saved(), [(3, date)])
        with application.get_db() as conn:
            conn.execute('UPDATE matches SET formation_id = 5 WHERE id = ?', (match_id,))
            conn.commit()
        rows = list(csv.DictReader(StringIO(
            self.client.get('/players/unavailability/export').data.decode('utf-8-sig'), newline='')))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['Player ID'], '3')
        self.assertEqual(rows[0]['Fixtures'], 'Town')
        self.assertEqual(rows[0]['Date'], (self.today + timedelta(days=1)).strftime('%d/%m/%Y'))

    def test_players_page_add_remove_and_export_filters_past(self):
        self.login()
        future = (self.today + timedelta(days=5)).isoformat()
        past = (self.today - timedelta(days=5)).isoformat()
        self.assertEqual(self.client.post('/players/1/unavailability', data={'unavailable_date': future}).status_code, 302)
        self.client.post('/players/1/unavailability', data={'unavailable_date': past})
        self.client.post('/players/1/unavailability', data={'unavailable_date': 'nonsense'})
        self.assertEqual(self.client.post('/players/999/unavailability', data={'unavailable_date': future}).status_code, 404)
        self.assertEqual(self.saved(), [(1, past), (1, future)])
        html = self.client.get('/players').get_data(as_text=True)
        self.assertIn('Saved unavailability', html)
        upcoming = self.client.get('/players/unavailability/export').data.decode('utf-8-sig')
        self.assertEqual(len(list(csv.DictReader(StringIO(upcoming)))), 1)
        everything = self.client.get('/players/unavailability/export?include_past=1').data.decode('utf-8-sig')
        self.assertEqual(len(list(csv.DictReader(StringIO(everything)))), 2)
        self.client.post(f'/players/1/unavailability/{future}/delete')
        self.assertEqual(self.saved(), [(1, past)])

    def test_routes_require_login(self):
        self.assertEqual(self.client.get('/players/unavailability/export').status_code, 302)
        self.assertEqual(self.client.post('/team-generator/save-availability').status_code, 302)


if __name__ == '__main__':
    unittest.main()
