import json
import unittest
from datetime import timedelta

import test_public_players as fixtures

application = fixtures.application


class GoalkeeperPageTests(unittest.TestCase):
    setUp = fixtures.PublicPlayerTests.setUp
    tearDown = fixtures.PublicPlayerTests.tearDown

    def login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True

    def date(self, days):
        return (self.today + timedelta(days=days)).isoformat()

    def fixture(self, days, opponent, formations=None):
        with application.get_db() as conn:
            formation_id = None
            if formations is not None:
                formation_id = conn.execute(
                    'INSERT INTO formations (name, data) VALUES (?, ?)',
                    (opponent, json.dumps({'formations': formations}))
                ).lastrowid
            match_id = conn.execute(
                'INSERT INTO matches (match_date, opponent, location, formation_id) VALUES (?, ?, ?, ?)',
                (self.date(days), opponent, 'Home', formation_id)
            ).lastrowid
            conn.commit()
            return match_id

    def add_goalkeeper(self):
        with application.get_db() as conn:
            conn.execute(
                'INSERT INTO players (id, name, position, status) VALUES (?, ?, ?, ?)',
                (6, 'Rory Keeper', 'GK', 'active')
            )
            conn.commit()

    def test_page_requires_login(self):
        response = self.client.get('/goalkeepers')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')

    def test_page_shows_in_goal_and_outfield_keeper_per_upcoming_fixture(self):
        self.add_goalkeeper()
        self.fixture(2, "Town's <script>", [{
            'players': [
                {'id': '1', 'name': 'Alex', 'position': 'GK'},
                {'id': '6', 'name': 'Rory Keeper', 'position': 'Outfield'},
                {'id': '2', 'name': 'Alex', 'position': 'DEF'},
            ],
            'subs': [],
        }])
        self.fixture(3, 'Awaiting team')
        self.fixture(-1, 'Past fixture', [{
            'players': [{'id': '1', 'name': 'Alex', 'position': 'GK'}], 'subs': []
        }])
        self.login()

        response = self.client.get('/goalkeepers')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('One keeper in goal', html)
        self.assertIn('Team not selected', html)
        self.assertIn('Alex', html)
        self.assertIn('Rory Keeper', html)
        self.assertIn('Outfield option', html)
        self.assertIn('vs Town&#39;s &lt;script&gt;', html)
        self.assertNotIn('Past fixture', html)
        self.assertIn('href="/goalkeepers"', html)

    def test_single_goalkeeper_is_marked_as_the_only_keeper_selected(self):
        self.fixture(1, 'One keeper', [{
            'players': [{'id': '1', 'name': 'Alex', 'position': 'GK'}], 'subs': []
        }])
        self.login()

        html = self.client.get('/goalkeepers').get_data(as_text=True)
        self.assertIn('Only keeper selected', html)
        self.assertIn('This is the only goalkeeper included in the saved team.', html)
        self.assertIn('None selected', html)

    def test_team_without_a_keeper_is_not_mistaken_for_an_unselected_team(self):
        self.fixture(1, 'No keeper', [{
            'players': [{'id': '2', 'name': 'Alex', 'position': 'DEF'}], 'subs': []
        }])
        self.login()

        html = self.client.get('/goalkeepers').get_data(as_text=True)
        self.assertIn('No keeper assigned', html)
        self.assertIn('No goalkeeper is assigned in goal.', html)
        self.assertNotIn('Team not selected', html)
