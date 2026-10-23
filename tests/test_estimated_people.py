from pathlib import Path
from datetime import datetime, timezone
import tempfile
import unittest
from unittest.mock import patch
import requests
from relleno.cameras import CameraError, CameraConnectionError, estimated_zero_day, request
from relleno.agent import collect_people


class EstimatedPeopleTests(unittest.TestCase):
    def camera(self):
        return dict(external_id='test-camera', ip='camera.test', name='Test', direction='bidirectional',
                    source_kind='people_counter', counting_enabled=True, region_id='1')

    @patch('relleno.agent.extract_day', side_effect=CameraConnectionError('offline'))
    def test_only_connection_failure_produces_stable_marked_zero(self, extract):
        with tempfile.TemporaryDirectory() as directory, patch('relleno.cameras.ROOT', Path(directory)):
            camera, first = collect_people(self.camera(), '2026-10-20', 'America/Santiago', 'test-centre')
            _, second = collect_people(self.camera(), '2026-10-20', 'America/Santiago', 'test-centre')
            self.assertEqual(first, second)
            self.assertTrue(first['quality']['estimated'])
            self.assertTrue(first['quality']['requires_manual_review'])
            self.assertEqual(len(first['intervals']), 24)
            self.assertTrue(all(r['entries'] == r['exits'] == 0 for r in first['intervals']))
            folder = Path(directory) / 'batches' / first['batch_id']
            self.assertTrue((folder / 'connection-error.json').is_file())
            self.assertTrue((folder / 'people.json').is_file())
            # Recovery must query the source again, rather than reuse an estimate as measured data.
            extract.side_effect = None
            extract.return_value = {'batch_id':'measured', 'intervals':[{'entries':7,'exits':3}]}
            _, real = collect_people(self.camera(), '2026-10-20', 'America/Santiago', 'test-centre')
            self.assertEqual(real['batch_id'], 'measured')
            self.assertNotEqual(real['batch_id'], first['batch_id'])

    @patch('relleno.agent.extract_day')
    @patch('relleno.agent.estimated_zero_day')
    def test_authentication_tls_and_incomplete_data_never_become_estimates(self, estimate, extract):
        for message in ('Wrong password', 'Changed certificate', 'Missing exits', 'HTTP 500'):
            extract.side_effect = CameraError(message)
            with self.assertRaises(CameraError):
                collect_people(self.camera(), '2026-10-20', 'America/Santiago', 'test-centre')
        estimate.assert_not_called()

    @patch('relleno.agent.probe', side_effect=CameraConnectionError('offline'))
    def test_pending_inventory_camera_is_sent_without_fabricating_model_or_identity(self, probe):
        with tempfile.TemporaryDirectory() as directory, patch('relleno.cameras.ROOT', Path(directory)):
            original = dict(self.camera(), source_kind='pending', direction='pending', counting_enabled=False)
            current, data = collect_people(original, '2026-10-20', 'America/Santiago', 'test-centre')
            self.assertEqual(current, original)
            self.assertEqual(data['camera']['external_id'], original['external_id'])
            self.assertEqual(data['camera']['ip'], original['ip'])
            self.assertEqual(data['source_kind'], 'people_counter')

    def test_dst_and_estimate_identity(self):
        with tempfile.TemporaryDirectory() as directory, patch('relleno.cameras.ROOT', Path(directory)):
            for day, expected in [('2026-09-06',23), ('2026-04-04',25)]:
                data = estimated_zero_day(self.camera(), day, 'America/Santiago', 'test-centre')
                self.assertEqual(len(data['intervals']), expected)
                for first, second in zip(data['intervals'],data['intervals'][1:]):
                    self.assertEqual(first['end'],second['start'])
                durations = [(datetime.fromisoformat(r['end']).astimezone(timezone.utc) -
                              datetime.fromisoformat(r['start']).astimezone(timezone.utc)).total_seconds()
                             for r in data['intervals']]
                self.assertTrue(all(seconds == 3600 for seconds in durations))
            first = estimated_zero_day(self.camera(), '2026-10-20', 'America/Santiago', 'test-centre')
            second = estimated_zero_day(self.camera(), '2026-10-20', 'America/Santiago', 'another-centre')
            self.assertNotEqual(first['batch_id'],second['batch_id'])

    @patch('relleno.cameras.read_secret', return_value={'username':'test','password':'test'})
    @patch('relleno.cameras.trust_local_camera_https', side_effect=CameraConnectionError('HTTPS offline'))
    @patch('relleno.cameras.requests.request', side_effect=requests.ConnectTimeout())
    def test_http_timeout_tries_https_before_allowing_estimate(self, send, trust, secret):
        with self.assertRaises(CameraConnectionError):
            request(self.camera(), '/ISAPI/System/deviceInfo')
        trust.assert_called_once()

    @patch('relleno.cameras.read_secret', return_value={'username':'test','password':'test'})
    @patch('relleno.cameras.requests.Session')
    @patch('relleno.cameras.requests.request')
    def test_failed_pinned_https_recovers_using_http(self, http, session, secret):
        session.return_value.request.side_effect = requests.ConnectTimeout()
        http.return_value.status_code = 200
        http.return_value.content = b'<ok/>'
        result = request(dict(self.camera(), https_fingerprint='a'*64), '/ISAPI/System/deviceInfo')
        self.assertEqual(result, b'<ok/>')
        self.assertTrue(http.call_args.args[1].startswith('http://'))

    @patch('relleno.agent.save')
    @patch('relleno.agent.send_batch', return_value='estimated-receipt')
    @patch('relleno.agent.probe', side_effect=CameraConnectionError('offline'))
    def test_remote_generation_delivers_pending_camera_estimate(self, probe, send, save):
        from relleno.agent import generate_people, capabilities
        with tempfile.TemporaryDirectory() as directory, patch('relleno.cameras.ROOT', Path(directory)):
            camera = dict(self.camera(), source_kind='pending', counting_enabled=False)
            config = {'cameras':[camera], 'binding':{'centre_id':'test-centre'}, 'timezone':'America/Santiago'}
            with patch('relleno.agent.read_secret', return_value=None):
                self.assertIn('personas', capabilities(config))
            self.assertEqual(generate_people(config,'2026-10-20'), ['estimated-receipt'])
            self.assertTrue(send.call_args.args[1]['quality']['estimated'])
            self.assertEqual(config['cameras'][0], camera)
