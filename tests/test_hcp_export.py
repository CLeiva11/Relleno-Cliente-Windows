from datetime import date, datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from relleno.anpr import Outbox
from relleno.hcp_export import download, export_day, login_controls, pending_days, ExportError
from relleno.anpr_schedule import Scheduler


class ExportTests(unittest.TestCase):
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
