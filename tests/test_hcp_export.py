from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from relleno.anpr import Outbox
from relleno.hcp_export import (download, export_day, login_controls, pending_days,
                                ANPR_COUNT_RESPONSE, HIKCENTRAL_UI, ExportError,
                                date_range_contains_day, dismiss_hikcentral_overlays,
                                select_all_anpr_cameras)
from relleno.anpr_schedule import Scheduler


class ExportTests(unittest.TestCase):
    @patch('relleno.hcp_export.visible_text')
    @patch('relleno.hcp_export.dismiss_hikcentral_overlays')
    @patch('relleno.hcp_export.ui_text')
    def test_hidden_anpr_is_opened_from_application_registry(self, ui, dismiss, visible):
        from relleno.hcp_export import open_anpr_search
        page = Mock()
        applications = page.locator.return_value.filter.return_value
        applications.count.return_value = 1
        anpr = visible.return_value
        anpr.count.side_effect = [0, 1]
        open_anpr_search(page, 'https://localhost')
        page.locator.assert_called_once_with('#navigation_addMenuBtn')
        applications.first.click.assert_called_once()
        anpr.first.wait_for.assert_called_once_with(timeout=15000)
        anpr.first.click.assert_called_once()
        page.goto.assert_not_called()

    @patch('relleno.hcp_export.visible_text')
    @patch('relleno.hcp_export.dismiss_hikcentral_overlays')
    @patch('relleno.hcp_export.ui_text')
    def test_registered_vehicle_catalogue_falls_back_to_anpr_search(self, ui, dismiss, visible):
        from relleno.hcp_export import open_anpr_search
        page = Mock()
        page.locator.return_value.filter.return_value.count.return_value = 0
        visible.return_value.count.return_value = 0
        module, search, root = Mock(), Mock(), Mock()
        module.count.return_value = 1
        search.first.wait_for.side_effect = TimeoutError('catalogue has no passing search')
        root.first.wait_for.side_effect = [TimeoutError('no camera tree'), None]
        ui.side_effect = lambda page, key: {'module':module, 'search_view':search, 'root':root}[key]
        open_anpr_search(page, 'https://localhost')
        page.goto.assert_called_once_with('https://localhost/#/anpr/vehicleSearch',
                                         wait_until='domcontentloaded', timeout=60000)
        self.assertEqual(root.first.wait_for.call_count, 2)

    @patch('relleno.hcp_export.visible_text')
    @patch('relleno.hcp_export.dismiss_hikcentral_overlays')
    @patch('relleno.hcp_export.ui_text')
    def test_legacy_camera_search_keeps_its_navigation(self, ui, dismiss, visible):
        from relleno.hcp_export import open_anpr_search
        page = Mock()
        page.locator.return_value.filter.return_value.count.return_value = 0
        visible.return_value.count.return_value = 0
        open_anpr_search(page, 'https://localhost')
        ui.return_value.first.click.assert_called()
        page.goto.assert_not_called()

    def test_hikcentral_profiles_cover_localized_routes(self):
        self.assertIn('Vehicles', HIKCENTRAL_UI['module'])
        self.assertTrue(ANPR_COUNT_RESPONSE.search('/api/anprVehicleTotal'))
        self.assertTrue(ANPR_COUNT_RESPONSE.search('/api/VehicleLogsCount'))

    def config(self):
        return {'binding':{'centre_id':'test-centre','agent_id':'test-agent','upload_url':'/api/anpr/'},
                'hikcentral':{'url':'https://localhost'},'timezone':'America/Santiago',
                'anpr':{'auto_export_enabled':True,'export_since':'2026-10-20'}}

    @patch('relleno.hcp_export.read_secret', return_value={'method':'username','account':'test','secret':'test-only'})
    @patch('relleno.hcp_export.check')
    @patch('relleno.hcp_export.download')
    def test_window_is_downloaded_once_and_original_is_retained(self, download, check, secret):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            def fake(config, day, credentials, folder):
                source = folder / 'ANPR-test.xlsx'
                source.write_bytes(b'PK\x03\x04unchanged native file')
                return source, {'count':3}
            download.side_effect = fake
            box = Outbox(root / 'queue')
            with patch('relleno.hcp_export.ROOT', root), patch('relleno.hcp_export.Outbox', return_value=box):
                first = export_day(self.config(), '2026-10-20')
                second = export_day(self.config(), '2026-10-20')
                self.assertEqual(first, second)
                self.assertEqual(download.call_count, 1)
                first.write_bytes(b'changed')
                with self.assertRaises(ExportError):
                    export_day(self.config(), '2026-10-20')

    def test_schedule_waits_until_one_am_and_keeps_missed_days(self):
        config = self.config()
        # UTC 03:30 is 00:30 in Santiago on this date.
        self.assertEqual(pending_days(config, datetime(2026,10,21,3,30,tzinfo=timezone.utc)), [])
        self.assertEqual(pending_days(config, datetime(2026,10,22,5,tzinfo=timezone.utc)), [date(2026,10,20),date(2026,10,21)])

    @patch('relleno.hcp_export._download', side_effect=RuntimeError('secret browser output'))
    def test_browser_errors_are_replaced_with_safe_stage(self, implementation):
        with self.assertRaisesRegex(ExportError, 'iniciar Microsoft Edge') as failure:
            download(self.config(), date(2026, 10, 20), {'account':'user','secret':'private'}, Path('.'))
        self.assertNotIn('secret browser output', str(failure.exception))

    @patch('relleno.hcp_export.time.monotonic', side_effect=[0, 0, 0, 0])
    def test_login_controls_are_found_inside_frame(self, clock):
        page = Mock()
        frame = Mock()
        page.frames = [frame]
        page.is_closed.return_value = False
        page.context.pages = [page]
        username = Mock()
        password = Mock()

        def locator(selector):
            collection = Mock()
            if selector == '#username':
                collection.count.return_value = 1
                collection.nth.return_value = username
                username.is_visible.return_value = True
            elif selector == '#password':
                collection.count.return_value = 1
                collection.nth.return_value = password
                password.is_visible.return_value = True
            else:
                collection.count.return_value = 0
            return collection

        frame.locator.side_effect = locator
        found_frame, found_user, found_password = login_controls(page, timeout_ms=1)
        self.assertIs(found_frame, frame)

        # HikCentral abre el login en otra pestaña y cierra la original.
        original = Mock()
        original.is_closed.return_value = True
        original.frames = []
        page.context.pages = [original, page]
        original.context = page.context
        found_frame, _user, _password = login_controls(original, timeout_ms=1)
        self.assertIs(found_frame, frame)
        self.assertIs(found_user, username)
        self.assertIs(found_password, password)

    @patch('relleno.anpr_schedule.pending_days', return_value=[date(2026,10,20)])
    @patch('relleno.anpr_schedule.export_and_enqueue', side_effect=ExportError('HikCentral no aceptó el inicio de sesión.'))
    def test_bad_login_does_not_loop(self, export, days):
        with tempfile.TemporaryDirectory() as directory:
            box = Outbox(directory)
            scheduler = Scheduler(box)
            scheduler.tick(self.config())
            scheduler.tick(self.config())
            self.assertEqual(export.call_count, 1)
            self.assertEqual(box.export_jobs()[0]['state'], 'blocked')

    @patch('relleno.anpr_schedule.pending_days', return_value=[date(2026,10,20)])
    def test_interrupted_window_is_recovered_after_restart(self, days):
        from relleno.hcp_export import export_key
        with tempfile.TemporaryDirectory() as directory:
            box = Outbox(directory)
            key = export_key(self.config(), date(2026,10,20))
            with box.connect() as db:
                db.execute("INSERT INTO export_jobs(job_key,day,state) VALUES (?,?,'exporting')",(key,'2026-10-20'))
            Scheduler(box)
            self.assertEqual(box.export_jobs()[0]['state'], 'pending')


class TypeIntoTests(unittest.TestCase):
    @patch('relleno.hcp_export.dismiss_hikcentral_overlays')
    @patch('relleno.hcp_export.tree_root_checked', side_effect=[False, False, True])
    def test_camera_tree_waits_for_loading_and_retries_selection(self, checked, dismiss):
        page = Mock()
        loading = Mock()
        page.get_by_text.return_value.filter.return_value = loading
        loading.count.side_effect = [1, 0]
        row = Mock()

        self.assertTrue(select_all_anpr_cameras(page, row, attempts=3))
        row.locator.return_value.first.click.assert_called_once()
        page.wait_for_timeout.assert_called_with(750)
        self.assertGreaterEqual(dismiss.call_count, 2)

    def test_applied_date_range_is_detected_after_calendar_closes(self):
        page = Mock()
        inputs = Mock()
        page.locator.return_value = inputs
        inputs.count.return_value = 2
        first = Mock()
        first.is_visible.return_value = True
        first.input_value.return_value = '2026/10/21 00:00:00 - 2026/10/21 23:59:59'
        second = Mock()
        second.is_visible.return_value = False
        inputs.nth.side_effect = [first, second]

        self.assertTrue(date_range_contains_day(page, date(2026, 10, 21)))

    def test_first_use_overlays_never_block_export(self):
        page = Mock()
        candidates = Mock()
        page.get_by_text.return_value.filter.return_value = candidates
        candidates.count.return_value = 1
        candidates.nth.return_value.click.side_effect = TimeoutError('covered')

        dismiss_hikcentral_overlays(page)

        self.assertEqual(page.get_by_text.call_count, 3)
        self.assertEqual(candidates.nth.return_value.click.call_count, 3)

    def test_readonly_field_is_enabled_after_focus_and_filled(self):
        from unittest.mock import Mock
        from relleno.hcp_export import type_into
        field = Mock()
        field.fill.side_effect = [TimeoutError('readonly'), None]
        progress = {}
        type_into(field, 'valor', progress)
        field.click.assert_called_once()
        field.evaluate.assert_called_once()
        self.assertEqual(field.fill.call_count, 2)
        self.assertNotIn('valor', ' '.join(progress['events']))
