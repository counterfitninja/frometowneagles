import json
import re
import unittest

import test_live_matches as fixtures


class ResultsTests(unittest.TestCase):
    setUp = fixtures.LiveMatchTests.setUp
    tearDown = fixtures.LiveMatchTests.tearDown
    fixture = fixtures.LiveMatchTests.fixture
    formation = fixtures.LiveMatchTests.formation
    page = fixtures.LiveMatchTests.page

    def results_config(self, html):
        raw = re.search(r'<script id="resultsConfig" type="application/json">(.*?)</script>', html, re.S)[1]
        self.assertNotIn('</script>', raw)
        return json.loads(raw)

    def test_results_require_manager_login(self):
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.get('/results').status_code, 302)

    def test_results_include_past_and_today_newest_first_but_not_future(self):
        old = self.fixture(-3)
        today = self.fixture()
        future = self.fixture(1)
        self.client.post(f'/api/matches/{old}/result', json={
            'goals': [{'scorer_id': '1', 'scorer': 'Alex', 'assist_id': '2', 'assist': 'Alex', 'at': 1000}],
            'opponentGoals': 1, 'opponentGoalTimes': [2000]
        })
        config = self.results_config(self.page('/results'))
        self.assertEqual([match['id'] for match in config], [today, old])
        self.assertNotIn(future, [match['id'] for match in config])
        self.assertFalse(config[0]['hasResult'])
        self.assertTrue(config[1]['hasResult'])
        self.assertEqual(config[1]['savedState']['opponentGoalTimes'], [2000])
        self.assertEqual(config[1]['savedState']['goals'][0]['at'], 1000)
        self.assertEqual(config[1]['storageKey'], f'matchResult_{old}')
        html = self.page('/results')
        self.assertIn('Not recorded', html)
        self.assertIn(f'/matches/{old}/live', html)
        self.assertIn('UK clock time', html)
        self.assertIn('Town&#39;s &lt;/script&gt;', html)

    def test_saved_zero_zero_is_a_result(self):
        match_id = self.fixture(-1)
        self.client.post(f'/api/matches/{match_id}/result', json={
            'goals': [], 'opponentGoals': 0, 'opponentGoalTimes': []
        })
        config = self.results_config(self.page('/results'))
        self.assertTrue(config[0]['hasResult'])
        self.assertIn('<span>0</span><span class="result-score-divider"> : </span><span>0</span>',
                      self.page('/results'))

    def test_empty_results_page_has_schedule_action(self):
        html = self.page('/results')
        self.assertIn('No past fixtures yet', html)
        self.assertIn('href="/matches"', html)
        self.assertEqual(self.results_config(html), [])

    def test_shared_formation_legacy_storage_cannot_be_attributed_to_wrong_fixture(self):
        formation_id = self.formation()
        first = self.fixture(-2, formation_id)
        second = self.fixture(-1, formation_id)
        config = self.results_config(self.page('/results'))
        for match in config:
            self.assertNotIn(f'matchDay_{formation_id}', match['legacyKeys'])
            self.assertEqual(match['legacyKeys'], [f'matchDay_match-{match["id"]}'])
        self.assertEqual([match['id'] for match in config], [second, first])

    def test_unique_formation_legacy_storage_is_available(self):
        formation_id = self.formation()
        match_id = self.fixture(-1, formation_id)
        config = self.results_config(self.page('/results'))
        self.assertEqual(config[0]['legacyKeys'], [f'matchDay_match-{match_id}', f'matchDay_{formation_id}'])

    def test_results_are_linked_from_navigation_live_and_leaderboard(self):
        match_id = self.fixture()
        for path in ('/matches', f'/matches/{match_id}/live', '/stats'):
            self.assertIn('href="/results"', self.page(path))

    def test_edit_opposition_times_preserves_all_other_result_fields(self):
        match_id = self.fixture(-1)
        payload = {
            'goals': [{'scorer_id': '1', 'scorer': 'Alex', 'assist_id': '2', 'assist': 'Alex', 'at': 1000}],
            'opponentGoals': 2, 'opponentGoalTimes': [None, None], 'motmPlayerId': '1'
        }
        self.client.post(f'/api/matches/{match_id}/result', json=payload)
        response = self.client.post(f'/api/matches/{match_id}/opposition-times',
                                    json={'times': [2000, None], 'previousTimes': [None, None]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(f'/api/matches/{match_id}/result').get_json(),
                         {**payload, 'opponentGoalTimes': [2000, None]})
        for data, code in [
            ({'times': [3000, None], 'previousTimes': [None, None]}, 409),
            ({'times': [], 'previousTimes': [2000, None]}, 409),
            ({'times': [True, None], 'previousTimes': [2000, None]}, 400),
            ({'times': [-1, None], 'previousTimes': [2000, None]}, 400),
            (None, 400)
        ]:
            self.assertEqual(self.client.post(f'/api/matches/{match_id}/opposition-times',
                                             json=data).status_code, code)
        self.assertEqual(self.client.get(f'/api/matches/{match_id}/result').get_json()['opponentGoalTimes'],
                         [2000, None])
        with self.client.session_transaction() as session:
            session.clear()
        self.assertEqual(self.client.post(f'/api/matches/{match_id}/opposition-times',
                                         json={'times': []}).status_code, 302)


if __name__ == '__main__':
    unittest.main()
