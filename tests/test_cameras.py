from datetime import date
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
from relleno.cameras import parse_counts, parse_inventory, CameraError, host_url


def report(entries='0', exits='3', count='1', start='2026-10-19T00:00:00', end='2026-10-19T00:59:59'):
    return f'<CountingStatisticsResult><responseStatus>true</responseStatus><numOfMatches>{count}</numOfMatches><matchList><matchElement><timeSpan><startTime>{start}</startTime><endTime>{end}</endTime></timeSpan><enterCount>{entries}</enterCount><exitCount>{exits}</exitCount></matchElement></matchList></CountingStatisticsResult>'.encode()


class CameraTests(unittest.TestCase):
    def test_zero_and_inclusive_end(self):
        row = parse_counts(report(), date(2026, 10, 19), ZoneInfo('America/Santiago'))[0]
        self.assertEqual(row['entries'], 0)
        self.assertEqual(row['exits'], 3)
        self.assertEqual(row['end'], '2026-10-19T01:00:00-03:00')

    def test_no_missing_negative_or_incomplete_values_become_zero(self):
        for raw in (report(entries=''), report(exits='-1'), report(count='2'), report().replace(b'<responseStatus>true', b'<responseStatus>false'), report().replace(b'<exitCount>3</exitCount>', b'')):
            with self.assertRaises(CameraError):
                parse_counts(raw, date(2026, 10, 19), ZoneInfo('America/Santiago'))

    def test_wrong_day_and_ambiguous_dst_are_rejected(self):
        with self.assertRaises(CameraError):
            parse_counts(report(), date(2026, 10, 18), ZoneInfo('America/Santiago'))
        with self.assertRaises(CameraError):
            parse_counts(report(start='2026-04-04T23:00:00', end='2026-04-04T23:59:59'), date(2026, 4, 4), ZoneInfo('America/Santiago'))

    def test_bulk_import_and_trailing_slash(self):
        cams = parse_inventory('Prueba;Nivel 0;Grupo;camera.invalid\\')
        self.assertEqual(cams[0]['ip'], 'camera.invalid')
        self.assertEqual(cams[0]['source_kind'], 'pending')
        self.assertEqual(cams[0]['location'], 'Nivel 0')
        with self.assertRaises(CameraError):
            parse_inventory('Prueba;Nivel 0;Grupo;camera.invalid\nPrueba 2;Nivel 0;Grupo;camera.invalid')

    def test_camera_address_cannot_contain_credentials(self):
        with self.assertRaises(CameraError):
            host_url('user:secret@camera.invalid')

    @patch('relleno.cameras.request')
    def test_source_is_kept_and_same_window_is_not_extracted_twice(self, request):
        from relleno.cameras import extract_day
        request.return_value = report()
        cam = dict(external_id='test-only', model='DS-2CD6825-test', source_kind='people_counter', counting_enabled=True, region_id='1', name='Prueba', ip='camera.invalid', region='r1', direction='bidirectional')
        with tempfile.TemporaryDirectory() as folder, patch('relleno.cameras.ROOT', Path(folder)):
            first = extract_day(cam, '2026-10-19', 'America/Santiago', 'test-centre')
            second = extract_day(cam, '2026-10-19', 'America/Santiago', 'test-centre')
            self.assertEqual(first, second)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(len(list(Path(folder).rglob('source-*.xml'))), 1)
            self.assertTrue(list(Path(folder).rglob('people.json')))


class ProbeCapabilityTests(unittest.TestCase):
    DEVICE = b'<DeviceInfo><serialNumber>SN1</serialNumber><model>iDS-2CD6810F</model><firmwareVersion>V5</firmwareVersion></DeviceInfo>'
    COUNTING = b'<Counting><enabled>true</enabled><CountingRegionList><CountingRegion><id>1</id></CountingRegion></CountingRegionList></Counting>'

    def probe(self, responses):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from relleno import cameras

        def fake_request(_camera, path, body=None):
            value = responses[path]
            if isinstance(value, Exception):
                raise value
            return value

        with tempfile.TemporaryDirectory() as root, \
                patch.object(cameras, 'request', side_effect=fake_request), \
                patch.object(cameras, 'read_secret', return_value={'username': 'u', 'password': 'p'}), \
                patch.object(cameras, 'store_secret'), patch.object(cameras, 'ROOT', Path(root)):
            return cameras.probe({'external_id': 'tmp', 'ip': '10.0.0.1', 'name': 'Acceso'})

    def test_other_model_with_isapi_counting_is_people_counter(self):
        cam = self.probe({'/ISAPI/System/deviceInfo': self.DEVICE,
                          '/ISAPI/System/Video/inputs/channels/1/counting': self.COUNTING})
        self.assertEqual(cam['source_kind'], 'people_counter')
        self.assertEqual(cam['region_id'], '1')
        self.assertTrue(cam['counting_enabled'])

    def test_camera_without_counting_is_not_people_counter(self):
        from relleno.cameras import CameraError
        cam = self.probe({'/ISAPI/System/deviceInfo': self.DEVICE,
                          '/ISAPI/System/Video/inputs/channels/1/counting': CameraError('HTTP 404')})
        self.assertEqual(cam['source_kind'], '')
        self.assertFalse(cam['counting_enabled'])
