import csv
import json
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

    def fixture_with_squad(self, days, player_ids, opponent='Town'):
        with application.get_db() as conn:
            cursor = conn.execute(
                'INSERT INTO formations (name, data) VALUES (?, ?)',
                (opponent, json.dumps({'formations': [{
                    'players': [{'id': player_id} for player_id in player_ids],
                    'subs': [],
                }]}))
            )
            match_id = conn.execute(
                'INSERT INTO matches (match_date, opponent, location, formation_id) VALUES (?, ?, ?, ?)',
                ((self.today + timedelta(days=days)).isoformat(), opponent, 'Home', cursor.lastrowid)
            ).lastrowid
            conn.commit()
            return match_id

    def saved(self):
        with application.get_db() as conn:
            return [tuple(row) for row in conn.execute(
                'SELECT player_id, unavailable_date FROM player_unavailability ORDER BY unavailable_date, player_id')]

    def checked(self, html, element_id):
        tag = re.search(r'<input\b[^>]*\bid="' + re.escape(element_id) + r'"[^>]*>', html)[0]
        return bool(re.search(r'\bchecked\b', tag))

    def public_form(self, player_id=1):
        html = self.client.get(f'/public/players/{player_id}').get_data(as_text=True)
        return {
            name: re.search(r'name="' + name + r'" value="([^"]*)"', html)[1]
            for name in ('csrf_token', 'availability_revision')
        }

    def public_update(self, action, player_id=1, **values):
        return self.client.post(f'/public/players/{player_id}', data={
            **self.public_form(player_id), 'action': action, **values,
        }, follow_redirects=True)

    def confirmed(self, player_id=1):
        return player_id in application.availability_confirmations()

    def test_parents_manage_shared_dates_without_login(self):
        future = (self.today + timedelta(days=5)).isoformat()
        html = self.public_update('add', unavailable_date=future).get_data(as_text=True)
        self.assertIn('Unavailable date saved.', html)
        self.assertIn(future, html)
        self.assertEqual(self.saved(), [(1, future)])
        self.public_update('add', unavailable_date=future)
        self.assertEqual(self.saved(), [(1, future)])
        # A fixture added later on that date uses the parent's saved availability.
        match_id = self.fixture(5)
        self.login()
        html = self.client.get('/team-generator').get_data(as_text=True)
        self.assertTrue(self.checked(html, f'unavailable-{match_id}-1'))
        self.assertIn('Awaiting confirmation', html)
        self.assertIn('href="/public/players/1#availability"', html)
        self.assertIn(future, self.client.get('/players').get_data(as_text=True))
        self.public_update('remove', unavailable_date=future)
        self.assertEqual(self.saved(), [])
        self.assertFalse(self.checked(self.client.get('/team-generator').get_data(as_text=True),
                                      f'unavailable-{match_id}-1'))

    def test_confirmation_requires_checkbox_and_supports_no_unavailable_dates(self):
        response = self.public_update('confirm')
        self.assertIn('Tick the checkbox', response.get_data(as_text=True))
        self.assertFalse(self.confirmed())
        html = self.public_update('confirm', availability_complete='yes').get_data(as_text=True)
        self.assertIn('Availability confirmed.', html)
        self.assertTrue(self.checked(html, 'availability-complete'))
        self.assertTrue(self.confirmed())
        self.login()
        html = self.client.get('/team-generator').get_data(as_text=True)
        self.assertIn('Parent availability confirmations (1/3)', html)
        self.assertIn('Confirmed ' + self.today.strftime('%d/%m/%Y'), html)

    def test_date_changes_clear_confirmation_but_duplicate_add_does_not(self):
        future = (self.today + timedelta(days=5)).isoformat()
        self.public_update('add', unavailable_date=future)
        self.public_update('confirm', availability_complete='yes')
        self.public_update('add', unavailable_date=future)
        self.assertTrue(self.confirmed())
        self.public_update('remove', unavailable_date=future)
        self.assertFalse(self.confirmed())
        self.public_update('confirm', availability_complete='yes')
        self.public_update('add', unavailable_date=future)
        self.assertFalse(self.confirmed())

    def test_manager_edits_and_generator_saves_invalidate_only_changed_players(self):
        match_id = self.fixture(5)
        future = (self.today + timedelta(days=5)).isoformat()
        self.public_update('confirm', availability_complete='yes')
        self.public_update('confirm', player_id=2, availability_complete='yes')
        self.login()
        self.client.post('/players/1/unavailability', data={'unavailable_date': future})
        self.assertFalse(self.confirmed())
        self.assertTrue(self.confirmed(2))
        self.public_update('confirm', availability_complete='yes')
        data = MultiDict([('match_ids', str(match_id)), (f'unavailable_for_{match_id}', '1')])
        self.client.post('/team-generator/save-availability', data=data)
        self.assertTrue(self.confirmed())
        self.client.post('/team-generator/save-availability', data={'match_ids': str(match_id)})
        self.assertFalse(self.confirmed())
        self.assertTrue(self.confirmed(2))
        self.client.post('/players/1/unavailability', data={'unavailable_date': future})
        self.public_update('confirm', availability_complete='yes')
        self.client.post(f'/players/1/unavailability/{future}/delete')
        self.assertFalse(self.confirmed())

    def test_stale_confirmation_cannot_confirm_dates_added_in_another_tab(self):
        form = self.public_form()
        self.public_update('add', unavailable_date=(self.today + timedelta(days=2)).isoformat())
        response = self.client.post('/public/players/1', data={
            **form, 'action': 'confirm', 'availability_complete': 'yes',
        }, follow_redirects=True)
        self.assertIn('dates changed', response.get_data(as_text=True))
        self.assertFalse(self.confirmed())

    def test_public_updates_validate_dates_tokens_and_active_player(self):
        for value in ('nonsense', '2026-02-30', (self.today - timedelta(days=1)).isoformat()):
            self.assertIn('Choose', self.public_update('add', unavailable_date=value).get_data(as_text=True))
        self.assertEqual(self.saved(), [])
        for token in ('', 'invalid'):
            response = self.client.post('/public/players/1', data={
                'csrf_token': token, 'action': 'add', 'unavailable_date': self.today.isoformat(),
            })
            self.assertEqual(response.status_code, 400)
        response = self.client.post('/public/players/1', data={**self.public_form(), 'action': 'unknown'})
        self.assertEqual(response.status_code, 400)
        with application.get_db() as conn:
            conn.execute("UPDATE players SET status = 'retired' WHERE id = 1")
            conn.commit()
        for player_id in (1, 999):
            self.assertEqual(self.client.post(f'/public/players/{player_id}', data={}).status_code, 404)

    def test_confirmation_expires_each_season_and_ignores_retired_players(self):
        self.public_update('confirm', availability_complete='yes')
        with application.get_db() as conn:
            conn.execute("UPDATE player_availability_confirmations SET season_start = '2000-09-01'")
            conn.commit()
        self.assertFalse(self.confirmed())
        html = self.client.get('/public/players/1').get_data(as_text=True)
        self.assertFalse(self.checked(html, 'availability-complete'))
        self.public_update('confirm', availability_complete='yes')
        with application.get_db() as conn:
            conn.execute("UPDATE players SET status = 'retired' WHERE id = 1")
            conn.commit()
        self.assertFalse(self.confirmed())

    def test_parent_dates_do_not_change_selected_teams_and_are_not_cached(self):
        self.fixture_with_squad(5, [1, 2])
        future = (self.today + timedelta(days=5)).isoformat()
        self.public_update('add', unavailable_date=future)
        with application.get_db() as conn:
            data = json.loads(conn.execute('SELECT data FROM formations').fetchone()['data'])
            self.assertEqual([p['id'] for p in data['formations'][0]['players']], [1, 2])
        response = self.client.get('/public/players/1')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')

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

    def test_players_page_always_shows_saved_squad_game_breakdown(self):
        self.login()
        self.fixture_with_squad(1, [1, 2], 'First team')
        first_date = (self.today + timedelta(days=1)).isoformat()
        self.client.post('/players/3/unavailability', data={'unavailable_date': first_date})
        self.fixture_with_squad(2, [2, 3], 'Second team')
        self.fixture(3, 'Team not saved')

        html = self.client.get('/players').get_data(as_text=True)
        summary_rows = {
            int(player_id): tuple(map(int, counts))
            for player_id, *counts in re.findall(
                r'<tr data-player-id="(\d+)">\s*<td>.*?</td>'
                r'\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>(\d+)</td>\s*<td[^>]*>(\d+)</td>',
                html,
                re.DOTALL,
            )
        }
        self.assertIn('Player game breakdown', html)
        self.assertIn('Upcoming games this season with a saved squad (2)', html)
        self.assertEqual(summary_rows, {
            1: (1, 1, 0),
            2: (2, 0, 0),
            3: (1, 0, 1),
        })

    def test_players_page_shows_breakdown_before_any_squad_is_saved(self):
        self.login()
        html = self.client.get('/players').get_data(as_text=True)
        self.assertIn('Player game breakdown', html)
        self.assertIn('Upcoming games this season with a saved squad (0)', html)

    def test_routes_require_login(self):
        self.assertEqual(self.client.get('/players/unavailability/export').status_code, 302)
        self.assertEqual(self.client.post('/team-generator/save-availability').status_code, 302)


if __name__ == '__main__':
    unittest.main()
