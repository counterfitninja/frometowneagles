import csv
from datetime import timedelta
from io import BytesIO, StringIO
import re
import unittest
from werkzeug.datastructures import MultiDict

import test_public_players as fixtures

application = fixtures.application


class AvailabilityExportTests(unittest.TestCase):
    setUp = fixtures.PublicPlayerTests.setUp
    tearDown = fixtures.PublicPlayerTests.tearDown

    def fixture(self, days, opponent='Town', location='Home', formation_id=None):
        with application.get_db() as conn:
            cursor = conn.execute('''
                INSERT INTO matches (match_date, opponent, location, formation_id)
                VALUES (?, ?, ?, ?)
            ''', ((self.today + timedelta(days=days)).isoformat(), opponent, location, formation_id))
            conn.commit()
            return cursor.lastrowid

    def export(self, values):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        return self.client.post('/team-generator/export-availability', data=MultiDict(values))

    def rows(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data.startswith(b'\xef\xbb\xbf'))
        return list(csv.DictReader(StringIO(response.data.decode('utf-8-sig'), newline='')))

    def test_exports_only_selected_fixtures_and_all_active_players(self):
        first = self.fixture(0)
        second = self.fixture(2, 'Another team', None)
        self.fixture(1, 'Unselected fixture')
        response = self.export([
            ('match_ids', str(second)), ('match_ids', str(first)),
            ('match_ids', str(first)), ('unavailable_for_' + str(first), '2'),
            ('unavailable_for_' + str(second), '3')
        ])
        rows = self.rows(response)
        self.assertEqual(len(rows), 6)
        self.assertEqual([row['Fixture ID'] for row in rows], [str(first)] * 3 + [str(second)] * 3)
        self.assertEqual([row['Player ID'] for row in rows[:3]], ['1', '2', '3'])
        self.assertEqual([row['Availability'] for row in rows],
                         ['Available', 'Unavailable', 'Available', 'Available', 'Available', 'Unavailable'])
        self.assertEqual(rows[0]['Date'], self.today.strftime('%d/%m/%Y'))
        self.assertEqual(rows[3]['Location'], '')
        self.assertEqual(response.mimetype, 'text/csv')
        self.assertIn('attachment; filename="player-availability-', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM formations').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM match_results').fetchone()[0], 0)

    def test_excludes_retired_players(self):
        with application.get_db() as conn:
            conn.execute("UPDATE players SET status = 'retired' WHERE id = 3")
            conn.commit()
        match_id = self.fixture(0)
        rows = self.rows(self.export([('match_ids', str(match_id))]))
        self.assertEqual([row['Player ID'] for row in rows], ['1', '2'])

    def test_preserves_quotes_commas_newlines_and_unicode(self):
        name = 'Renée, "Keeper"\nJunior'
        with application.get_db() as conn:
            conn.execute('UPDATE players SET name = ? WHERE id = 1', (name,))
            conn.commit()
        match_id = self.fixture(0, 'Town, "United"', 'Pitch\nTwo')
        rows = self.rows(self.export([('match_ids', str(match_id))]))
        player = next(row for row in rows if row['Player ID'] == '1')
        self.assertEqual(player['Player'], name)
        self.assertEqual(player['Opponent'], 'Town, "United"')
        self.assertEqual(player['Location'], 'Pitch\nTwo')

    def test_neutralizes_spreadsheet_formulas(self):
        with application.get_db() as conn:
            conn.execute('UPDATE players SET name = ?, position = ? WHERE id = 1',
                         ('=1+1', '\t=1+1'))
            conn.commit()
        match_id = self.fixture(0, '  +1+1', '@SUM(1,1)')
        rows = self.rows(self.export([('match_ids', str(match_id))]))
        player = next(row for row in rows if row['Player ID'] == '1')
        self.assertEqual(player['Player'], "'=1+1")
        self.assertEqual(player['Position'], "'\t=1+1")
        self.assertEqual(player['Opponent'], "'  +1+1")
        self.assertEqual(player['Location'], "'@SUM(1,1)")

    def test_requires_fixture_selection_and_preserves_current_ticks_on_error(self):
        match_id = self.fixture(0)
        response = self.export([])
        self.assertEqual(response.status_code, 400)
        self.assertIn('Select at least one fixture', response.get_data(as_text=True))
        response = self.export([
            ('match_ids', str(match_id)), ('match_ids', '999'),
            ('unavailable_for_' + str(match_id), '2')
        ])
        self.assertEqual(response.status_code, 400)
        html = response.get_data(as_text=True)
        self.assertIn('no longer available', html)
        self.assertRegex(html, rf'id="unavailable-{match_id}-2"[\s\S]*?checked')

    def test_rejects_stale_fixture_or_player_selections(self):
        match_id = self.fixture(0, formation_id=99)
        response = self.export([('match_ids', str(match_id))])
        self.assertEqual(response.status_code, 400)
        self.assertIn('no longer available', response.get_data(as_text=True))
        available_id = self.fixture(1)
        response = self.export([
            ('match_ids', str(available_id)), ('unavailable_for_' + str(available_id), '999')
        ])
        self.assertEqual(response.status_code, 400)
        self.assertIn('no longer active', response.get_data(as_text=True))

    def test_reports_empty_active_squad(self):
        match_id = self.fixture(0)
        with application.get_db() as conn:
            conn.execute("UPDATE players SET status = 'retired'")
            conn.commit()
        response = self.export([('match_ids', str(match_id))])
        self.assertEqual(response.status_code, 400)
        self.assertIn('Add active players', response.get_data(as_text=True))

    def test_export_does_not_require_valid_generation_settings(self):
        match_id = self.fixture(0)
        rows = self.rows(self.export([
            ('match_ids', str(match_id)), ('team_size', 'invalid'), ('num_games', 'invalid')
        ]))
        self.assertEqual(len(rows), 3)

    def test_download_is_authenticated_and_accessible_under_more(self):
        match_id = self.fixture(0)
        self.assertEqual(self.client.post('/team-generator/export-availability',
                                          data={'match_ids': str(match_id)}).status_code, 302)
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        html = self.client.get('/team-generator').get_data(as_text=True)
        self.assertIn('Export availability (CSV)', html)
        self.assertIn('formaction="/team-generator/export-availability" formnovalidate', html)
        self.assertIn('if (exportButton) exportButton.disabled = selectedCount === 0', html)

    def import_csv(self, contents, values=()):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        data = MultiDict(values)
        data.add('availability_file', (BytesIO(contents), 'availability.csv'))
        response = self.client.post('/team-generator/import-availability', data=data,
                                    content_type='multipart/form-data')
        response.request.close()
        response.request.environ['wsgi.input'].close()
        return response

    def checked(self, html, element_id):
        tag = re.search(r'<input\b[^>]*\bid="' + re.escape(element_id) + r'"[^>]*>', html)[0]
        return bool(re.search(r'\bchecked\b', tag))

    def test_export_import_export_round_trip_preserves_exact_selections(self):
        first = self.fixture(0)
        second = self.fixture(1)
        third = self.fixture(2)
        original = self.export([
            ('match_ids', str(first)), ('match_ids', str(second)),
            (f'unavailable_for_{first}', '1'), (f'unavailable_for_{second}', '2'),
            (f'unavailable_for_{second}', '3')
        ])
        response = self.import_csv(original.data, [
            ('match_ids', str(third)), (f'unavailable_for_{third}', '3'), ('team_size', '11')
        ])
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('Imported availability for 2 fixture(s)', html)
        self.assertIn('enctype="multipart/form-data"', html)
        self.assertIn('formaction="/team-generator/import-availability"', html)
        self.assertTrue(self.checked(html, f'game-{first}'))
        self.assertTrue(self.checked(html, f'game-{second}'))
        self.assertFalse(self.checked(html, f'game-{third}'))
        restored = []
        for match_id in (first, second):
            restored.append(('match_ids', str(match_id)))
            for player_id in (1, 2, 3):
                if self.checked(html, f'unavailable-{match_id}-{player_id}'):
                    restored.append((f'unavailable_for_{match_id}', str(player_id)))
        self.assertEqual(self.export(restored).data, original.data)
        with application.get_db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM formations').fetchone()[0], 0)
        fresh_html = self.client.get('/team-generator').get_data(as_text=True)
        self.assertFalse(self.checked(fresh_html, f'unavailable-{first}-1'))

    def test_import_uses_ids_with_duplicate_names_and_spreadsheet_edits(self):
        match_id = self.fixture(0, '=Town')
        exported = self.export([('match_ids', str(match_id))])
        rows = self.rows(exported)
        rows[1]['Availability'] = ' unavailable '
        rows[0]['Player'] = 'Renamed display name'
        output = StringIO(newline='')
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
        response = self.import_csv(output.getvalue().encode('utf-8'))
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertFalse(self.checked(html, f'unavailable-{match_id}-1'))
        self.assertTrue(self.checked(html, f'unavailable-{match_id}-2'))

    def test_invalid_import_is_atomic_and_preserves_current_ticks(self):
        match_id = self.fixture(0)
        valid = self.export([('match_ids', str(match_id))]).data.decode('utf-8-sig')
        invalid_files = [
            (b'', 'columns'),
            (b'\xff\xfe', 'UTF-8'),
            (b'Fixture ID,Player ID,Availability\n"unterminated', 'UTF-8'),
            (b'Fixture ID,Player ID,Availability,Availability\n', 'duplicate column'),
            (b'Fixture ID,Player ID,Availability\n', 'no player availability'),
            (f'Fixture ID,Player ID,Availability\n{match_id},1,Available\n'.encode(), 'every active player'),
            (valid.replace(',Available', ',Maybe', 1).encode(), 'must be Available'),
            (valid.replace(f'{match_id},', '999,', 1).encode(), 'no longer available'),
            (valid.encode() + valid.splitlines()[1].encode() + b'\r\n', 'duplicate player'),
            (f'Fixture ID,Player ID,Availability\n{match_id},999,Available\n'.encode(), 'no longer active'),
            (f'Fixture ID,Player ID,Availability\n{match_id},1\n'.encode(), 'missing or extra'),
            (f'Fixture ID,Player ID,Availability\n{match_id},1,Available,extra\n'.encode(), 'missing or extra'),
            (b'x' * (2 * 1024 * 1024 + 1), '2 MB')
        ]
        for contents, message in invalid_files:
            with self.subTest(message=message):
                response = self.import_csv(contents, [
                    ('match_ids', str(match_id)), (f'unavailable_for_{match_id}', '2')
                ])
                self.assertEqual(response.status_code, 400)
                html = response.get_data(as_text=True)
                self.assertIn(message, html)
                self.assertTrue(self.checked(html, f'unavailable-{match_id}-2'))
                self.assertFalse(self.checked(html, f'unavailable-{match_id}-1'))
                self.assertNotIn('Imported availability', html)

    def test_import_rejects_stale_players_and_assigned_fixtures(self):
        match_id = self.fixture(0)
        data = self.export([('match_ids', str(match_id))]).data
        with application.get_db() as conn:
            conn.execute("UPDATE players SET status = 'retired' WHERE id = 3")
            conn.commit()
        self.assertIn('no longer active', self.import_csv(data).get_data(as_text=True))
        with application.get_db() as conn:
            conn.execute("UPDATE players SET status = 'active' WHERE id = 3")
            conn.execute('UPDATE matches SET formation_id = 99 WHERE id = ?', (match_id,))
            conn.commit()
        self.assertIn('no longer available', self.import_csv(data).get_data(as_text=True))

    def test_import_requires_login_and_a_file(self):
        response = self.client.post('/team-generator/import-availability')
        self.assertEqual(response.status_code, 302)
        with self.client.session_transaction() as session:
            session['logged_in'] = True
        response = self.client.post('/team-generator/import-availability')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Choose an exported availability CSV', response.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
