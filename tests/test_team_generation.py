import json
import re
import unittest
from collections import Counter
from datetime import date, datetime, timedelta
from unittest.mock import patch
from werkzeug.datastructures import MultiDict

import test_public_players as fixtures

application = fixtures.application


class TeamGenerationTests(unittest.TestCase):
    setUp = fixtures.PublicPlayerTests.setUp
    tearDown = fixtures.PublicPlayerTests.tearDown

    def prepare(self, games=4):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        with application.get_db() as conn:
            conn.execute("INSERT INTO players (id, name, position) VALUES (4, 'Blake', 'GK')")
            conn.executemany('INSERT INTO players (id, name, position) VALUES (?, ?, ?)',
                             [(pid, f'Player {pid}', 'MID') for pid in range(5, 17)])
            for day in range(games):
                conn.execute('INSERT INTO matches (match_date, opponent) VALUES (?, ?)',
                             ((self.today + timedelta(days=day)).isoformat(), f'Town {day}'))
            conn.commit()

    def generate(self, extra=(), games=4):
        values = [('team_size', '9'), ('num_games', str(games))]
        values.extend(('match_ids', str(pid)) for pid in range(1, games + 1))
        response = self.client.post('/team-generator/generate', data=MultiDict(values + list(extra)))
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def teams(self, html):
        match = re.search(r'\n    generatedTeams = (\[.*?\]);', html)
        self.assertIsNotNone(match, html)
        return json.loads(match.group(1))

    def test_keeper_percentages_apply_only_to_games_in_goal(self):
        self.prepare()
        teams = self.teams(self.generate([
            ('goalkeeper_percentage_1', '75'), ('goalkeeper_percentage_4', '25')]))
        counts = Counter(p['id'] for team in teams for p in team['starters'] + team['subs'])
        goal_counts = Counter(team['starters'][0]['id'] for team in teams)
        self.assertEqual(goal_counts[1], 3)
        self.assertEqual(goal_counts[4], 1)
        self.assertEqual(counts[1], 3)
        self.assertIn(counts[4], (2, 3))
        self.assertLessEqual(max(counts[pid] for pid in range(1, 17)) -
                             min(counts[pid] for pid in range(1, 17)), 1)
        for team in teams:
            self.assertEqual(len(team['starters']), 9)
            self.assertEqual(sum(p['position'] == 'GK' for p in team['starters']), 1)
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM formations').fetchone()[0], 0)

    def test_keepers_share_rest_rotation_over_many_games(self):
        self.prepare(games=20)
        for _ in range(10):
            teams = self.teams(self.generate([
                ('goalkeeper_percentage_1', '50'), ('goalkeeper_percentage_4', '50')], games=20))
            counts = Counter(p['id'] for team in teams for p in team['starters'] + team['subs'])
            self.assertEqual(Counter(team['starters'][0]['id'] for team in teams), {1: 10, 4: 10})
            self.assertEqual(sum(counts.values()), 180)
            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
            for team in teams:
                selected = team['starters'] + team['subs']
                self.assertEqual(len({p['id'] for p in selected}), 9)
                self.assertEqual(len(team['not_playing']), 7)
                self.assertEqual(sum(p['position'] == 'GK' for p in selected), 1)
            for keeper_id in (1, 4):
                self.assertGreater(counts[keeper_id], 10)
                self.assertIn(20 - counts[keeper_id], (8, 9))

    def test_keeper_fixtures_are_randomised_without_changing_targets(self):
        self.prepare(games=20)

        def shuffle(values):
            if values == list(range(20)):
                values[:] = values[::2] + values[1::2]

        with patch('random.shuffle', side_effect=shuffle) as mocked_shuffle:
            teams = self.teams(self.generate([
                ('goalkeeper_percentage_1', '50'),
                ('goalkeeper_percentage_4', '50')], games=20))

        keeper_ids = [team['starters'][0]['id'] for team in teams]
        self.assertEqual(Counter(keeper_ids), {1: 10, 4: 10})
        self.assertTrue(all(first != second for first, second in zip(keeper_ids, keeper_ids[1:])))
        self.assertTrue(any(call.args[0] == list(range(0, 20, 2)) + list(range(1, 20, 2))
                            for call in mocked_shuffle.call_args_list))

    def test_zero_goal_target_keeper_can_play_outfield_and_saved_role_is_preserved(self):
        self.prepare()
        teams = self.teams(self.generate([
            ('goalkeeper_percentage_1', '100'), ('goalkeeper_percentage_4', '0')]))
        appearances = [(team, player) for team in teams for player in team['starters'] + team['subs']
                       if player['id'] == 4]
        self.assertGreater(len(appearances), 0)
        self.assertLess(len(appearances), 4)
        self.assertTrue(all(player['position'] == 'Outfield' for team, player in appearances))
        team = appearances[0][0]
        response = self.client.post('/formations/save', json={
            'name': 'Mixed roles', 'match_id': team['match_id'], 'private_team': True,
            'data': json.dumps({'formations': [{'players': team['starters'], 'subs': team['subs']}]})})
        self.assertTrue(response.json['success'])
        with application.get_db() as conn:
            formation = json.loads(conn.execute('SELECT data FROM formations WHERE id=?',
                                                (response.json['id'],)).fetchone()[0])['formations'][0]
            keeper = next(p for p in formation['players'] + formation['subs'] if p['id'] == 4)
            self.assertEqual(keeper['position'], 'Outfield')
            self.assertEqual(conn.execute('SELECT position FROM players WHERE id=4').fetchone()[0], 'GK')

    def test_multiple_keepers_can_fill_normal_outfield_places(self):
        self.prepare(games=1)
        with application.get_db() as conn:
            conn.execute("UPDATE players SET position='GK'")
            conn.commit()
        teams = self.teams(self.generate(games=1))
        selected = teams[0]['starters'] + teams[0]['subs']
        self.assertEqual(len(selected), 9)
        self.assertEqual(sum(p['position'] == 'GK' for p in selected), 1)
        self.assertEqual(sum(p['position'] == 'Outfield' for p in selected), 8)

    def test_shared_rotation_respects_availability_and_invite_all(self):
        self.prepare()
        teams = self.teams(self.generate([
            ('goalkeeper_percentage_1', '67'), ('goalkeeper_percentage_4', '33'),
            ('unavailable_for_1', '4'), ('unavailable_for_2', '4'),
            ('unavailable_for_3', '2'), ('invite_all_for', '4')]))
        self.assertEqual(Counter(team['starters'][0]['id'] for team in teams[:3]), {1: 2, 4: 1})
        for index, unavailable in ((0, 4), (1, 4), (2, 2)):
            selected = teams[index]['starters'] + teams[index]['subs']
            self.assertNotIn(unavailable, [p['id'] for p in selected])
            self.assertNotIn(unavailable, [p['id'] for p in teams[index]['not_playing']])
            self.assertIn(unavailable, [p['id'] for p in teams[index]['unavailable']])
        selected = teams[3]['starters'] + teams[3]['subs']
        self.assertEqual(len(selected), 16)
        self.assertEqual(sum(p['position'] == 'GK' for p in selected), 1)
        self.assertEqual(teams[3]['not_playing'], [])

    def test_rounds_targets_to_whole_games_and_accepts_zero(self):
        self.prepare(games=3)
        teams = self.teams(self.generate([
            ('goalkeeper_percentage_1', '50'), ('goalkeeper_percentage_4', '50')], games=3))
        counts = Counter(p['id'] for team in teams for p in team['starters'] if p['position'] == 'GK')
        self.assertEqual(sorted(counts.values()), [1, 2])
        teams = self.teams(self.generate([
            ('goalkeeper_percentage_1', '100'), ('goalkeeper_percentage_4', '0')], games=3))
        self.assertTrue(all(team['starters'][0]['id'] == 1 for team in teams))

    def test_availability_reassigns_keeper_slots(self):
        self.prepare()
        teams = self.teams(self.generate([
            ('goalkeeper_percentage_1', '50'), ('goalkeeper_percentage_4', '50'),
            ('unavailable_for_3', '4'), ('unavailable_for_4', '4')]))
        self.assertEqual([team['starters'][0]['id'] for team in teams], [4, 4, 1, 1])
        html = self.generate([
            ('goalkeeper_percentage_1', '100'), ('goalkeeper_percentage_4', '0'),
            ('unavailable_for_1', '1')])
        self.assertIn('targets cannot cover', html)
        self.assertNotIn('\n    generatedTeams = [', html)

    def test_rejects_invalid_percentages_and_preserves_inputs(self):
        self.prepare()
        for value in ('-1', '101', 'abc', '50.5', '70'):
            html = self.generate([('goalkeeper_percentage_1', value), ('goalkeeper_percentage_4', '25')])
            self.assertIn('Error:', html)
            self.assertNotIn('\n    generatedTeams = [', html)
        self.assertIn('value="70"', html)
        html = self.generate([('goalkeeper_percentage_1', '75')])
        self.assertIn('totalling 100%', html)

    def test_invite_all_overrides_targets_and_default_rotates_equally(self):
        self.prepare()
        teams = self.teams(self.generate())
        self.assertEqual(Counter(team['starters'][0]['id'] for team in teams), {1: 2, 4: 2})
        teams = self.teams(self.generate([
            ('goalkeeper_percentage_1', '100'), ('goalkeeper_percentage_4', '0'),
            ('invite_all_for', '1')]))
        self.assertEqual(len(teams[0]['starters'] + teams[0]['subs']), 16)
        self.assertTrue(all(team['starters'][0]['id'] == 1 for team in teams[1:]))

    def test_drafts_stay_hidden_until_published_and_can_be_hidden_again(self):
        self.prepare(games=1)
        formation = json.dumps({'formations': [{'players': [{'id': 1}], 'subs': [{'id': 4}]}]})
        response = self.client.post('/formations/save', json={
            'name': 'Secret draft name', 'data': formation, 'match_id': 1, 'private_team': True})
        self.assertTrue(response.json['success'])
        formation_id = response.json['id']
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT team_published FROM matches WHERE id=1').fetchone()[0], 0)
        for published in (False, True, False):
            response = self.client.post('/matches/1/publication', data={'published': str(int(published))})
            self.assertEqual(response.status_code, 302)
            html = self.client.get('/public/overview').get_data(as_text=True)
            self.assertEqual('Town 0' in html, published)
            html = self.client.get('/public/next-match').get_data(as_text=True)
            self.assertEqual('No team selected for this match' in html, not published)
            self.assertNotIn('Secret draft name', html)
            html = self.client.get('/public/players/2').get_data(as_text=True)
            self.assertEqual('Town 0' in html.split('<h2 id="unselected-heading">')[0], published)
        response = self.client.post('/formations/save', json={
            'id': formation_id, 'name': 'Edited draft', 'data': formation, 'match_id': 1})
        self.assertTrue(response.json['success'])
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT team_published FROM matches WHERE id=1').fetchone()[0], 0)
        html = self.client.get('/matches').get_data(as_text=True)
        self.assertIn('Private draft', html)
        self.assertIn('Publish team', html)

    def test_custom_draft_linking_is_private_and_publication_requires_login(self):
        self.prepare(games=1)
        response = self.client.post('/formations/save', json={
            'name': 'Draft', 'data': '{"formations": []}', 'private_team': True})
        self.client.post(f"/matches/1/link-formation/{response.json['id']}")
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT team_published FROM matches WHERE id=1').fetchone()[0], 0)
        self.assertEqual(self.client.post('/matches/1/publication', data={'published': 'yes'}).status_code, 400)
        self.assertEqual(self.client.post('/matches/999/publication', data={'published': '1'}).status_code, 404)
        self.client.get('/logout')
        for path in ('/team-generator', '/formations/1/load', '/matches/1/publication'):
            response = self.client.post(path) if path.endswith('publication') else self.client.get(path)
            self.assertEqual(response.status_code, 302)

    def test_pitch_save_links_drafts_privately_without_unpublishing_existing_team(self):
        self.prepare(games=1)
        response = self.client.post('/formations/save', json={
            'name': 'Draft', 'data': '{"formations": []}', 'private_team': True})
        formation_id = response.json['id']
        for published in (0, 1):
            if published:
                self.client.post('/matches/1/publication', data={'published': '1'})
            response = self.client.post('/formations/save', json={
                'id': formation_id, 'name': 'Edited', 'data': '{"formations": []}', 'match_id': 1})
            self.assertTrue(response.json['success'])
            with application.get_db() as conn:
                self.assertEqual(conn.execute('SELECT team_published FROM matches WHERE id=1').fetchone()[0],
                                 published)

    def test_invalid_match_does_not_leave_orphaned_draft(self):
        self.prepare(games=1)
        response = self.client.post('/formations/save', json={
            'name': 'Draft', 'data': '{"formations": []}', 'match_id': 999, 'private_team': True})
        self.assertEqual(response.status_code, 404)
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM formations').fetchone()[0], 0)

    def test_single_keeper_and_all_keeper_invite_fixture(self):
        self.prepare(games=1)
        with application.get_db() as conn:
            conn.execute("UPDATE players SET position = 'MID' WHERE id=4")
            conn.commit()
        teams = self.teams(self.generate([('goalkeeper_percentage_1', '100')], games=1))
        self.assertEqual(teams[0]['starters'][0]['id'], 1)
        with application.get_db() as conn:
            conn.execute("UPDATE players SET position = 'GK'")
            conn.commit()
        teams = self.teams(self.generate([('invite_all_for', '1')], games=1))
        self.assertEqual(len(teams[0]['starters'] + teams[0]['subs']), 16)

    def test_migration_preserves_existing_publication_and_drafts(self):
        self.prepare(games=1)
        with application.get_db() as conn:
            conn.execute('DROP TABLE matches')
            conn.execute('''
                CREATE TABLE matches (
                    id INTEGER PRIMARY KEY, match_date TEXT NOT NULL,
                    opponent TEXT NOT NULL, location TEXT, formation_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            conn.execute('INSERT INTO matches (id, match_date, opponent) VALUES (1, ?, ?)',
                         (self.today.isoformat(), 'Legacy match'))
            conn.commit()
        application.init_db()
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT team_published FROM matches WHERE id=1').fetchone()[0], 1)
            conn.execute('UPDATE matches SET team_published=0 WHERE id=1')
            conn.commit()
        application.init_db()
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT team_published FROM matches WHERE id=1').fetchone()[0], 0)

    def regeneration_clock(self):
        self.today = date(2026, 10, 5)
        clock = patch.object(application, 'datetime', wraps=datetime)
        mocked = clock.start()
        mocked.now.return_value = datetime(2026, 10, 5)
        self.addCleanup(clock.stop)

    def save_season_teams(self):
        old_ids = []
        with application.get_db() as conn:
            for match_id in range(1, 5):
                cursor = conn.execute(
                    'INSERT INTO formations (name, data) VALUES (?, ?)',
                    (f'Old {match_id}', '{"formations": []}')
                )
                old_ids.append(cursor.lastrowid)
                conn.execute('UPDATE matches SET formation_id=? WHERE id=?',
                             (cursor.lastrowid, match_id))
            conn.commit()
        return old_ids

    def test_season_starts_on_september_first(self):
        for today, start, end in (
                (date(2026, 8, 31), '2025-09-01', '2026-09-01'),
                (date(2026, 9, 1), '2026-09-01', '2027-09-01'),
                (date(2027, 1, 1), '2026-09-01', '2027-09-01')):
            self.assertEqual(application.current_season_bounds(today),
                             (today.isoformat(), start, end))

    def test_generate_again_replaces_only_upcoming_season_teams_privately(self):
        self.regeneration_clock()
        self.prepare()
        old_ids = self.save_season_teams()
        with application.get_db() as conn:
            for match_date in ('2026-08-31', '2026-09-01', '2026-10-04', '2027-09-01'):
                conn.execute('INSERT INTO matches (match_date, opponent, formation_id) VALUES (?, ?, ?)',
                             (match_date, 'Kept fixture', old_ids[0]))
            conn.execute('INSERT INTO player_unavailability (player_id, unavailable_date) VALUES (2, ?)',
                         (self.today.isoformat(),))
            conn.commit()
        html = self.client.get('/team-generator?regenerate=1').get_data(as_text=True)
        self.assertIn('Generate again', html)
        self.assertIn('id="unavailable-1-2"', html)
        self.assertNotIn('Kept fixture', html)
        values = [('team_size', '9'), ('goalkeeper_percentage_1', '75'),
                  ('goalkeeper_percentage_4', '25'), ('unavailable_for_1', '2')]
        values.extend(('match_ids', str(match_id)) for match_id in range(1, 5))
        response = self.client.post('/team-generator/regenerate', data=MultiDict(values))
        self.assertEqual(response.status_code, 200)
        teams = self.teams(response.get_data(as_text=True))
        self.assertEqual(Counter(team['starters'][0]['id'] for team in teams), {1: 3, 4: 1})
        self.assertNotIn(2, [player['id'] for player in teams[0]['starters'] + teams[0]['subs']])
        with application.get_db() as conn:
            upcoming = conn.execute('SELECT formation_id, team_published FROM matches WHERE id<=4').fetchall()
            self.assertTrue(all(row['formation_id'] not in old_ids and row['team_published'] == 0
                                for row in upcoming))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM formations WHERE id IN (?, ?, ?)',
                                          tuple(old_ids[1:])).fetchone()[0], 0)
            kept = conn.execute('SELECT formation_id, team_published FROM matches WHERE id>4').fetchall()
            self.assertTrue(all(row['formation_id'] == old_ids[0] and row['team_published'] == 1
                                for row in kept))
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM player_unavailability').fetchone()[0], 1)
            stored = json.loads(conn.execute('SELECT data FROM formations WHERE id=?',
                                            (upcoming[0]['formation_id'],)).fetchone()[0])
            self.assertEqual(len(stored['formations'][0]['players']), 9)
        html = self.client.get('/team-generator?regenerate=1').get_data(as_text=True)
        self.assertIn('value="75"', html)
        self.assertIn('value="25"', html)

    def test_failed_regeneration_keeps_existing_teams_and_availability(self):
        self.regeneration_clock()
        self.prepare()
        old_ids = self.save_season_teams()
        values = [('team_size', '9'), ('goalkeeper_percentage_1', '100'),
                  ('goalkeeper_percentage_4', '0'), ('unavailable_for_1', '1')]
        values.extend(('match_ids', str(match_id)) for match_id in range(1, 5))
        html = self.client.post('/team-generator/regenerate', data=MultiDict(values)).get_data(as_text=True)
        self.assertIn('targets cannot cover', html)
        with application.get_db() as conn:
            self.assertEqual([row[0] for row in conn.execute('SELECT formation_id FROM matches ORDER BY id')],
                             old_ids)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM formations').fetchone()[0], 4)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM player_unavailability').fetchone()[0], 0)

    def test_regeneration_requires_login_and_all_current_fixtures(self):
        self.regeneration_clock()
        self.prepare()
        html = self.client.post('/team-generator/regenerate', data={
            'team_size': '9', 'match_ids': '1'
        }).get_data(as_text=True)
        self.assertIn('Review all upcoming fixtures', html)
        self.client.get('/logout')
        self.assertEqual(self.client.post('/team-generator/regenerate').status_code, 302)

    def test_regeneration_covers_a_season_longer_than_twenty_games(self):
        self.regeneration_clock()
        self.prepare(games=21)
        response = self.client.post('/team-generator/regenerate', data=MultiDict(
            [('team_size', '9')] + [('match_ids', str(match_id)) for match_id in range(1, 22)]
        ))
        self.assertEqual(len(self.teams(response.get_data(as_text=True))), 21)
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM matches WHERE formation_id IS NOT NULL')
                             .fetchone()[0], 21)


if __name__ == '__main__':
    unittest.main()
