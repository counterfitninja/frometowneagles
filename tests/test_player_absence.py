import json
import re
import unittest
from datetime import timedelta
from urllib.parse import urlencode

import test_public_players as fixtures

application = fixtures.application


class PlayerAbsenceTests(unittest.TestCase):
    setUp = fixtures.PublicPlayerTests.setUp
    tearDown = fixtures.PublicPlayerTests.tearDown

    def login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def date(self, days):
        return (self.today + timedelta(days=days)).isoformat()

    def fixture(self, days=1, selections=None, formation_id=None):
        with application.get_db() as conn:
            if selections is not None:
                formation_id = conn.execute(
                    'INSERT INTO formations (name, data) VALUES (?, ?)',
                    ('Original team', json.dumps({'formations': selections, 'custom': 'keep'}))
                ).lastrowid
            match_id = conn.execute(
                'INSERT INTO matches (match_date, opponent, location, formation_id) VALUES (?, ?, ?, ?)',
                (self.date(days), 'Town <script>', 'Home', formation_id)
            ).lastrowid
            conn.commit()
            return match_id

    def squad(self, days=1, player_id=2):
        return self.fixture(days, [{
            'name': 'First half',
            'players': [{'id': '1', 'name': 'Alex', 'position': 'GK'},
                        {'id': str(player_id), 'name': 'Alex', 'position': 'DEF',
                         'xPercent': 25, 'yPercent': 50}],
            'subs': [],
        }])

    def preview(self, player_id=2, start=1, end=3):
        self.login()
        response = self.client.get('/players/absence?' + urlencode({
            'player_id': player_id, 'start_date': self.date(start), 'end_date': self.date(end)
        }))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        fields = {
            name: re.search(r'name="' + name + r'" value="([^"]*)"', html)[1]
            for name in ('csrf_token', 'revision', 'player_id', 'start_date', 'end_date')
        }
        return html, fields

    def team(self, match_id):
        with application.get_db() as conn:
            row = conn.execute('''
                SELECT m.*, f.data, f.private_team
                FROM matches m JOIN formations f ON f.id = m.formation_id WHERE m.id = ?
            ''', (match_id,)).fetchone()
            return dict(row), json.loads(row['data'])

    def saved_dates(self):
        with application.get_db() as conn:
            return [tuple(row) for row in conn.execute(
                'SELECT player_id, unavailable_date FROM player_unavailability ORDER BY player_id, unavailable_date'
            )]

    def test_review_and_no_extra_saves_whole_range_and_private_draft(self):
        match_id = self.squad()
        past_id = self.squad(-1)
        future_id = self.squad(4)
        original, _ = self.team(match_id)
        html, data = self.preview()
        self.assertIn('Town &lt;script&gt;', html)
        self.assertIn("Don't bring anyone extra", html)
        self.assertIn('2 selected &rarr; 1', html)
        self.assertEqual(self.saved_dates(), [])
        self.assertEqual(self.team(match_id)[0]['formation_id'], original['formation_id'])
        response = self.client.post('/players/absence', data={
            **data, f'replacement_{match_id}': 'none'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('1 squad(s) updated as private drafts', response.get_data(as_text=True))
        row, saved = self.team(match_id)
        self.assertNotEqual(row['formation_id'], original['formation_id'])
        self.assertEqual((row['private_team'], row['team_published']), (1, 0))
        self.assertEqual(saved['formations'][0]['players'], [{'id': '1', 'name': 'Alex', 'position': 'GK'}])
        self.assertEqual(saved['custom'], 'keep')
        self.assertEqual(self.saved_dates(), [(2, self.date(day)) for day in range(1, 4)])
        for unaffected_id in (past_id, future_id):
            self.assertEqual(len(self.team(unaffected_id)[1]['formations'][0]['players']), 2)
            self.assertEqual(self.team(unaffected_id)[0]['team_published'], 1)
        self.assertNotIn((2, self.date(4)), self.saved_dates())

    def test_replacement_inherits_slots_in_every_variation_and_shared_team_unchanged(self):
        match_id = self.fixture(selections=[
            {'players': [{'id': '2', 'position': 'DEF', 'xPercent': 25, 'yPercent': 30}], 'subs': []},
            {'players': [], 'subs': [{'id': 2, 'position': 'DEF'}], 'squad': [{'id': '2'}]},
        ])
        original, _ = self.team(match_id)
        shared_id = self.fixture(2, formation_id=original['formation_id'])
        html, data = self.preview(end=1)
        self.assertIn('Sam &lt;script&gt;', html)
        self.assertEqual(self.client.post('/players/absence', data={
            **data, f'replacement_{match_id}': '3'
        }).status_code, 302)
        _, saved = self.team(match_id)
        replacement = saved['formations'][0]['players'][0]
        self.assertEqual(replacement, {'id': '3', 'name': 'Sam <script>', 'position': 'MID',
                                      'xPercent': 25, 'yPercent': 30})
        self.assertEqual(saved['formations'][1]['subs'][0]['id'], '3')
        self.assertEqual(saved['formations'][1]['squad'][0]['id'], '3')
        self.assertEqual(self.team(shared_id)[0]['formation_id'], original['formation_id'])
        self.assertEqual(self.team(shared_id)[1]['formations'][0]['players'][0]['id'], '2')

    def test_suggestions_rank_position_then_fewer_selections_and_exclude_ineligible(self):
        with application.get_db() as conn:
            conn.executemany(
                'INSERT INTO players (id, name, position, status) VALUES (?, ?, ?, ?)',
                [(4, 'Regular defender', 'DEF', 'active'), (5, 'Rested defender', 'DEF', 'active'),
                 (6, 'Retired defender', 'DEF', 'retired'), (7, 'Away defender', 'DEF', 'active')]
            )
            conn.execute('INSERT INTO player_unavailability (player_id, unavailable_date) VALUES (7, ?)',
                         (self.date(1),))
            conn.commit()
        match_id = self.squad()
        self.fixture(4, selections=[{'players': [{'id': 4}]}])
        html, _ = self.preview()
        select = re.search(rf'<select id="replacement-{match_id}".*?</select>', html, re.S)[0]
        self.assertEqual(re.findall(r'<option value="([^"]+)"', select), ['none', '5', '4', '3'])

    def test_goalkeeping_place_offers_only_available_keepers(self):
        match_id = self.fixture(selections=[{'players': [{'id': '1', 'position': 'GK'}]}])
        with application.get_db() as conn:
            conn.execute("INSERT INTO players (id, name, position) VALUES (4, 'Other keeper', 'GK')")
            conn.commit()
        html, data = self.preview(player_id=1)
        select = re.search(rf'<select id="replacement-{match_id}".*?</select>', html, re.S)[0]
        self.assertEqual(re.findall(r'<option value="([^"]+)"', select), ['none', '4'])
        self.assertIn('arrange cover', html)
        self.assertEqual(self.client.post('/players/absence', data={
            **data, f'replacement_{match_id}': '2'
        }).status_code, 400)
        self.assertEqual(self.saved_dates(), [])

    def test_outfield_keeper_can_be_replaced_by_outfielder(self):
        match_id = self.fixture(selections=[{'players': [{'id': '1', 'position': 'Outfield'}]}])
        html, data = self.preview(player_id=1)
        self.assertIn('value="2"', html)
        self.assertEqual(self.client.post('/players/absence', data={
            **data, f'replacement_{match_id}': '2'
        }).status_code, 302)
        self.assertEqual(self.team(match_id)[1]['formations'][0]['players'][0]['position'], 'DEF')

    def test_no_selected_player_and_new_fixtures_keep_saved_availability(self):
        unaffected = self.squad()
        _, data = self.preview(player_id=3)
        original, _ = self.team(unaffected)
        response = self.client.post('/players/absence', data=data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.team(unaffected)[0]['formation_id'], original['formation_id'])
        self.assertEqual(self.saved_dates(), [(3, self.date(day)) for day in range(1, 4)])
        added = self.fixture(2)
        html = self.client.get('/team-generator').get_data(as_text=True)
        self.assertRegex(html, rf'id="unavailable-{added}-3"[^>]*checked')

    def test_empty_schedule_saves_dates_and_clears_confirmation(self):
        _, season_start, _ = application.current_season_bounds()
        with application.get_db() as conn:
            conn.execute('''
                INSERT INTO player_availability_confirmations (player_id, season_start, confirmed_at)
                VALUES (2, ?, 'today')
            ''', (season_start,))
            conn.commit()
        html, data = self.preview()
        self.assertIn('No fixtures in these dates', html)
        self.assertEqual(self.client.post('/players/absence', data=data).status_code, 302)
        self.assertEqual(self.saved_dates(), [(2, self.date(day)) for day in range(1, 4)])
        self.assertNotIn(2, application.availability_confirmations())

    def test_invalid_decision_is_atomic_across_multiple_fixtures(self):
        first = self.squad()
        second = self.squad(2)
        _, data = self.preview()
        original, _ = self.team(first)
        response = self.client.post('/players/absence', data={
            **data, f'replacement_{first}': '3', f'replacement_{second}': '999'
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved_dates(), [])
        self.assertEqual(self.team(first)[0]['formation_id'], original['formation_id'])

    def test_stale_review_rejected_for_schedule_squad_availability_or_roster_change(self):
        match_id = self.squad()
        changes = [
            ("UPDATE matches SET opponent = 'Changed' WHERE id = ?", (match_id,)),
            ("UPDATE formations SET data = ? WHERE id = ?",
             ('{"formations": []}', self.team(match_id)[0]['formation_id'])),
            ('INSERT INTO player_unavailability (player_id, unavailable_date) VALUES (3, ?)', (self.date(1),)),
            ("UPDATE players SET status = 'retired' WHERE id = 3", ()),
        ]
        for query, params in changes:
            with self.subTest(query=query):
                _, data = self.preview()
                with application.get_db() as conn:
                    conn.execute(query, params)
                    conn.commit()
                response = self.client.post('/players/absence', data={
                    **data, f'replacement_{match_id}': 'none'
                })
                self.assertEqual(response.status_code, 409)
                self.assertIn('changed. Review the updated choices', response.get_data(as_text=True))
                self.assertNotIn(2, {pid for pid, _ in self.saved_dates()})

    def test_auth_csrf_and_invalid_ranges(self):
        self.assertEqual(self.client.get('/players/absence').status_code, 302)
        self.assertEqual(self.client.post('/players/absence').status_code, 302)
        self.login()
        self.assertEqual(self.client.post('/players/absence').status_code, 400)
        for start, end, player_id in [
            (self.date(-1), self.date(1), 2),
            (self.date(2), self.date(1), 2),
            ('invalid', self.date(1), 2),
            (self.date(1), self.date(367), 2),
            (self.date(1), self.date(2), 999),
        ]:
            response = self.client.get('/players/absence?' + urlencode({
                'player_id': player_id, 'start_date': start, 'end_date': end
            }))
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.saved_dates(), [])

    def test_tampered_range_requires_new_review(self):
        _, data = self.preview()
        response = self.client.post('/players/absence', data={**data, 'end_date': self.date(4)})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.saved_dates(), [])


if __name__ == '__main__':
    unittest.main()
