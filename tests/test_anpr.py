from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests

from relleno.anpr import Outbox, file_hash


class AnprTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.source = self.root / 'original.xlsx'
        self.content = b'PK\x03\x04original export bytes - not rewritten'
        self.source.write_bytes(self.content)
        self.box = Outbox(self.root / 'queue')
        self.binding = dict(centre_id='test-centre', agent_id='test-agent', upload_url='/api/comprobaciones/agentes/anpr/')
        self.config = {'binding': self.binding}
        self.session = Mock()
        self.response = self.session.post.return_value
        self.response.status_code = 200
        self.response.text = '{"ok":true,"receipt_id":"test-receipt"}'
        self.response.json.return_value = {'ok': True, 'receipt_id': 'test-receipt'}
        self.secret = patch('relleno.anpr.read_secret', return_value={'token': 'test-only-token'})
        self.secret.start()

    def tearDown(self):
        self.secret.stop()
        self.directory.cleanup()

    def add(self):
        return self.box.add(self.source, self.binding)

    def test_identical_files_are_deduplicated_without_rewriting(self):
        batch = self.add()
        other = self.root / 'other-name.xlsx'
        other.write_bytes(self.content)
        self.assertEqual(self.box.add(other, self.binding), batch)
        rows = self.box.list()
        self.assertEqual(len(rows), 1)
        self.assertEqual(Path(rows[0]['spool_path']).read_bytes(), self.content)
        self.assertEqual(file_hash(self.source), rows[0]['sha256'])

    def test_receipt_is_saved_and_delivered_file_is_not_sent_twice(self):
        self.add()
        def post(url, **kwargs):
            self.assertEqual(url, 'https://siem.domoticatechnology.cl/relleno/api/comprobaciones/agentes/anpr/')
            self.assertFalse(kwargs['allow_redirects'])
            field, (name, handle, mime) = kwargs['files'][0]
            self.assertEqual(field, 'source_files')
            self.assertEqual(handle.read(), self.content)
            self.assertEqual(name, self.source.name)
            self.assertEqual(kwargs['headers']['Idempotency-Key'], self.box.list()[0]['batch_id'])
            return self.response
        self.session.post.side_effect = post
        self.box.drain(self.config, self.session)
        row = self.box.list()[0]
        self.assertEqual((row['state'], row['receipt_id']), ('delivered', 'test-receipt'))
        self.assertTrue(Path(row['spool_path']).exists())
        self.box.drain(self.config, self.session)
        self.assertEqual(self.session.post.call_count, 1)

    def test_unauthorized_is_not_automatically_retried(self):
        self.add()
        self.response.status_code = 401
        self.box.drain(self.config, self.session)
        self.box.drain(self.config, self.session)
        self.assertEqual(self.box.list()[0]['state'], 'blocked')
        self.assertEqual(self.session.post.call_count, 1)

    def test_ambiguous_failure_is_not_blindly_repeated(self):
        self.add()
        self.session.post.side_effect = requests.ReadTimeout()
        self.box.drain(self.config, self.session)
        self.box.drain(self.config, self.session)
        self.assertEqual(self.box.list()[0]['state'], 'uncertain')
        self.assertEqual(self.session.post.call_count, 1)

    def test_connect_failure_is_backed_off_and_persisted(self):
        self.add()
        self.session.post.side_effect = requests.ConnectTimeout()
        self.box.drain(self.config, self.session)
        row = Outbox(self.root / 'queue').list()[0]
        self.assertEqual(row['state'], 'pending')
        self.assertGreater(row['next_attempt'], 0)
        self.box.drain(self.config, self.session)
        self.assertEqual(self.session.post.call_count, 1)

    def test_crash_after_send_requires_receipt_review(self):
        batch = self.add()
        self.box.update(batch, 'sending', 'test')
        self.box.drain(self.config, self.session)
        self.assertEqual(self.box.list()[0]['state'], 'uncertain')
        self.session.post.assert_not_called()

    def test_tampered_local_source_is_not_sent(self):
        self.add()
        Path(self.box.list()[0]['spool_path']).write_bytes(b'changed')
        self.box.drain(self.config, self.session)
        self.assertEqual(self.box.list()[0]['state'], 'blocked')
        self.session.post.assert_not_called()

    def test_success_without_receipt_is_not_delivered(self):
        self.add()
        self.response.json.return_value = {'ok': True}
        self.box.drain(self.config, self.session)
        self.assertEqual(self.box.list()[0]['state'], 'uncertain')

    def test_other_centre_is_not_sent(self):
        self.add()
        self.box.drain({'binding': self.binding | {'centre_id':'other'}}, self.session)
        self.session.post.assert_not_called()

    def test_processing_error_keeps_receipt_and_warns_without_resending(self):
        self.add()
        self.response.json.return_value = {'ok': True, 'receipt': {
            'id': 'receipt-rejected-rows', 'status': 'comparison_error',
            'total_rows': 100, 'valid_rows': 0}}
        self.box.drain(self.config, self.session)
        row = self.box.list()[0]
        self.assertEqual(row['receipt_id'], 'receipt-rejected-rows')
        self.assertEqual(row['state'], 'delivered')
        self.assertIn('revisar', row['message'])
        self.box.drain(self.config, self.session)
        self.assertEqual(self.session.post.call_count, 1)
