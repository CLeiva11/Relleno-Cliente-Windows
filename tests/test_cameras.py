from datetime import date
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo
from relleno.cameras import (is_local_camera_host, parse_counts, parse_inventory, request,
                             supported_counting_model, counting_query_profile, query_variants,
                             CameraError, host_url)


def report(entries='0', exits='3', count='1', start='2026-10-19T00:00:00', end='2026-10-19T00:59:59'):
    return f'<CountingStatisticsResult><responseStatus>true</responseStatus><numOfMatches>{count}</numOfMatches><matchList><matchElement><timeSpan><startTime>{start}</startTime><endTime>{end}</endTime></timeSpan><enterCount>{entries}</enterCount><exitCount>{exits}</exitCount></matchElement></matchList></CountingStatisticsResult>'.encode()


class CameraTests(unittest.TestCase):
    def test_supported_counting_models_are_case_insensitive(self):
        self.assertTrue(supported_counting_model('DS-2CD6825G0/C-IVS'))
        self.assertTrue(supported_counting_model('iDS-2CD7146G0-IZS'))
        self.assertFalse(supported_counting_model('DS-2CD7A46G0/P-IZHSY'))
    def test_zero_and_inclusive_end(self):
        row = parse_counts(report(), date(2026, 10, 19), ZoneInfo('America/Santiago'))[0]
        self.assertEqual(row['entries'], 0)
        self.assertEqual(row['exits'], 3)
        self.assertEqual(row['end'], '2026-10-19T01:00:00-03:00')

    def test_no_missing_negative_or_incomplete_values_become_zero(self):
        for raw in (report(entries=''), report(exits='-1'), report(count='2'), report().replace(b'<responseStatus>true', b'<responseStatus>false'), report().replace(b'<exitCount>3</exitCount>', b'')):
            with self.assertRaises(CameraError):
                parse_counts(raw, date(2026, 10, 19), ZoneInfo('America/Santiago'))

    def test_failed_statistics_include_hikvision_status(self):
        raw = b'<CountingStatisticsResult><responseStatus>false</responseStatus><statusString>Invalid XML Content</statusString></CountingStatisticsResult>'
        with self.assertRaisesRegex(CameraError, 'Invalid XML Content'):
            parse_counts(raw, date(2026, 10, 19), ZoneInfo('America/Santiago'))

    def test_legacy_count_aliases_and_missing_optional_status_are_supported(self):
        raw = report(entries='7', exits='9').replace(b'<responseStatus>true</responseStatus>', b'')
        raw = raw.replace(b'enterCount', b'enterNum').replace(b'exitCount', b'exitNum')
        row = parse_counts(raw, date(2026, 10, 19), ZoneInfo('America/Santiago'))[0]
        self.assertEqual((row['entries'], row['exits']), (7, 9))

    def test_capabilities_prioritize_legacy_region_body(self):
        profile = counting_query_profile(
            b'<CountingCap><regionID opt="1,2"/><reportType opt="daily"/></CountingCap>'
        )
        self.assertEqual(query_variants({'counting_query_profile': profile}, '1')[0],
                         ('regionID', '1', False))

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

    @patch('relleno.cameras.read_secret', return_value={'username': 'user', 'password': 'secret'})
    @patch('relleno.cameras.requests.request')
    def test_redirect_to_web_login_has_actionable_error(self, send, secret):
        send.return_value = Mock(
            status_code=302,
            headers={'Location': '/doc/page/login.asp'},
            url='http://192.168.1.20/ISAPI/System/deviceInfo',
        )
        camera = {'external_id': '20', 'ip': '192.168.1.20'}
        with self.assertRaisesRegex(CameraError, 'login web.*Digest'):
            request(camera, '/ISAPI/System/deviceInfo')

    @patch('relleno.cameras.read_camera_certificate_fingerprint', return_value='ab' * 32)
    @patch('relleno.cameras.read_secret', return_value={'username': 'user', 'password': 'secret'})
    @patch('relleno.cameras.requests.Session')
    @patch('relleno.cameras.requests.request')
    def test_private_camera_https_redirect_is_pinned_and_retried(self, send, session, secret, fingerprint):
        send.return_value = Mock(
            status_code=302,
            headers={'Location': 'https://192.168.1.20/ISAPI/System/deviceInfo'},
            url='http://192.168.1.20/ISAPI/System/deviceInfo',
        )
        session.return_value.request.return_value = Mock(
            status_code=200, content=b'<DeviceInfo/>', headers={},
            url='https://192.168.1.20/ISAPI/System/deviceInfo',
        )
        camera = {'external_id': '20', 'ip': '192.168.1.20'}
        self.assertEqual(request(camera, '/ISAPI/System/deviceInfo'), b'<DeviceInfo/>')
        self.assertEqual(camera['https_fingerprint'], 'ab' * 32)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(session.return_value.request.call_count, 1)

    @patch('relleno.cameras.read_camera_certificate_fingerprint', return_value='cd' * 32)
    @patch('relleno.cameras.is_local_camera_host', return_value=True)
    @patch('relleno.cameras.read_secret', return_value={'username': 'user', 'password': 'secret'})
    @patch('relleno.cameras.requests.Session')
    @patch('relleno.cameras.requests.request', side_effect=__import__('requests').exceptions.ConnectionError)
    def test_https_only_local_camera_is_pinned_automatically(self, send, session, secret, local, fingerprint):
        session.return_value.request.return_value = Mock(
            status_code=200, content=b'<DeviceInfo/>', headers={},
            url='https://192.168.1.20/ISAPI/System/deviceInfo',
        )
        camera = {'external_id': '20', 'ip': '192.168.1.20'}

        self.assertEqual(request(camera, '/ISAPI/System/deviceInfo'), b'<DeviceInfo/>')
        self.assertEqual(camera['https_fingerprint'], 'cd' * 32)
        fingerprint.assert_called_once_with('192.168.1.20')

    @patch('relleno.cameras.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('192.168.1.20', 443))])
    def test_local_camera_host_accepts_only_private_resolution(self, resolve):
        self.assertTrue(is_local_camera_host('camera.local'))
        resolve.return_value = [(2, 1, 6, '', ('8.8.8.8', 443))]
        self.assertFalse(is_local_camera_host('camera.example'))

    @patch('relleno.cameras.read_secret', return_value={'username': 'user', 'password': 'secret'})
    @patch('relleno.cameras.requests.Session')
    def test_confirmed_fingerprint_uses_pinned_https(self, session, secret):
        session.return_value.request.return_value = Mock(
            status_code=200, content=b'<DeviceInfo/>', headers={},
            url='https://192.168.1.20/ISAPI/System/deviceInfo',
        )
        camera = {'external_id': '20', 'ip': '192.168.1.20', 'https_fingerprint': 'ab' * 32}
        self.assertEqual(request(camera, '/ISAPI/System/deviceInfo'), b'<DeviceInfo/>')
        self.assertEqual(
            session.return_value.request.call_args.args[1],
            'https://192.168.1.20/ISAPI/System/deviceInfo',
        )
        self.assertFalse(session.return_value.request.call_args.kwargs['verify'])
        session.return_value.mount.assert_called_once()

    @patch('relleno.cameras.request')
    def test_source_is_kept_and_same_window_is_not_extracted_twice(self, request):
        from relleno.cameras import extract_day
        request.return_value = report()
        cam = dict(external_id='test-only', model='DS-2CD6825-test', source_kind='people_counter', counting_enabled=True, region_id='1', name='Prueba', ip='camera.invalid', region='r1', direction='bidirectional')
        with tempfile.TemporaryDirectory() as folder, patch('relleno.cameras.ROOT', Path(folder)):
            first = extract_day(cam, '2026-10-19', 'America/Santiago', 'test-centre')
            second = extract_day(cam, '2026-10-19', 'America/Santiago', 'test-centre')
            self.assertEqual(first, second)
            self.assertNotIn('region', first['camera'])
            self.assertEqual(request.call_count, 1)
            self.assertEqual(len(list(Path(folder).rglob('source-*.xml'))), 1)
            self.assertTrue(list(Path(folder).rglob('people.json')))

    @patch('relleno.cameras.request')
    def test_global_counting_fallback_omits_region_id(self, request):
        from relleno.cameras import extract_day
        failed = b'<CountingStatisticsResult><responseStatus>false</responseStatus><statusString>Invalid regionID</statusString></CountingStatisticsResult>'
        request.side_effect = [failed, report()]
        cam = dict(external_id='global-test', model='iDS-2CD7146G0-IZS', source_kind='people_counter',
                   counting_enabled=True, region_id='1', channel_id='1', name='Prueba',
                   ip='camera.invalid', region='r1', direction='bidirectional')
        with tempfile.TemporaryDirectory() as folder, patch('relleno.cameras.ROOT', Path(folder)):
            result = extract_day(cam, '2026-10-19', 'America/Santiago', 'test-centre')
        self.assertEqual(result['intervals'][0]['exits'], 3)
        first_body = request.call_args_list[0].args[2]
        second_body = request.call_args_list[1].args[2]
        self.assertIn(b'<regionsID>1</regionsID>', first_body)
        self.assertIn(b'<MinTimeInterval>hour</MinTimeInterval>', first_body)
        self.assertNotIn(b'<regionsID>', second_body)
        self.assertNotIn(b'<child>', first_body)

    @patch('relleno.cameras.request')
    def test_unsupported_xml_http_error_uses_next_safe_variant(self, request):
        from relleno.cameras import extract_day
        request.side_effect = [CameraError('La cámara respondió HTTP 415.'), report()]
        cam = dict(external_id='http-fallback', model='DS-2CD6825', source_kind='people_counter',
                   counting_enabled=True, region_id='1', channel_id='1', name='Prueba',
                   ip='camera.invalid', direction='bidirectional')
        with tempfile.TemporaryDirectory() as folder, patch('relleno.cameras.ROOT', Path(folder)):
            result = extract_day(cam, '2026-10-19', 'America/Santiago', 'test-centre')
        self.assertEqual(result['intervals'][0]['exits'], 3)
        self.assertEqual(request.call_count, 2)


class ProbeCapabilityTests(unittest.TestCase):
    DEVICE = b'<DeviceInfo><serialNumber>SN1</serialNumber><model>iDS-2CD6810F</model><firmwareVersion>V5</firmwareVersion></DeviceInfo>'
    COUNTING = b'<Counting><enabled>true</enabled><CountingRegionList><CountingRegion><id>1</id></CountingRegion></CountingRegionList></Counting>'

    def probe(self, responses):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from relleno import cameras

        def fake_request(_camera, path, body=None):
            value = responses.get(path, cameras.CameraError('La cámara respondió HTTP 404.'))
            if isinstance(value, Exception):
                raise value
            return value

        with tempfile.TemporaryDirectory() as root, \
                patch.object(cameras, 'request', side_effect=fake_request), \
                patch.object(cameras, 'read_secret', return_value={'username': 'u', 'password': 'p'}), \
                patch.object(cameras, 'store_secret'), patch.object(cameras, 'ROOT', Path(root)):
            camera = cameras.probe({'external_id': 'tmp', 'ip': '10.0.0.1', 'name': 'Acceso'})
            self.saved = sorted(p.name for p in Path(root).rglob('*.xml'))
            return camera

    def test_other_model_with_isapi_counting_is_people_counter(self):
        cam = self.probe({'/ISAPI/System/deviceInfo': self.DEVICE,
                          '/ISAPI/System/Video/inputs/channels/1/counting': self.COUNTING})
        self.assertEqual(cam['source_kind'], 'people_counter')
        self.assertEqual(cam['region_id'], '1')
        self.assertTrue(cam['counting_enabled'])

    def test_deepinview_global_rule_defaults_to_region_one(self):
        device = b'<DeviceInfo><serialNumber>SN2</serialNumber><model>iDS-2CD7146G0-IZS</model></DeviceInfo>'
        counting = b'<Counting><enabled>true</enabled></Counting>'
        cam = self.probe({'/ISAPI/System/deviceInfo': device,
                          '/ISAPI/System/Video/inputs/channels/1/counting': counting})
        self.assertEqual(cam['region_id'], '1')
        self.assertTrue(cam['counting_model_supported'])

    def test_camera_without_counting_is_not_people_counter(self):
        from relleno.cameras import CameraError
        cam = self.probe({'/ISAPI/System/deviceInfo': self.DEVICE,
                          '/ISAPI/System/Video/inputs/channels/1/counting': CameraError('HTTP 404')})
        self.assertEqual(cam['source_kind'], '')
        self.assertFalse(cam['counting_enabled'])

    def test_counting_found_on_second_channel_and_capabilities_saved(self):
        channels = b'<VideoInputChannelList><VideoInputChannel><id>1</id></VideoInputChannel><VideoInputChannel><id>2</id></VideoInputChannel></VideoInputChannelList>'
        cam = self.probe({'/ISAPI/System/deviceInfo': self.DEVICE,
                          '/ISAPI/System/Video/inputs/channels': channels,
                          '/ISAPI/System/Video/inputs/channels/2/counting': self.COUNTING,
                          '/ISAPI/Smart/capabilities': b'<SmartCap><isSupportFaceDetect>true</isSupportFaceDetect></SmartCap>'})
        self.assertEqual(cam['channel_id'], '2')
        self.assertEqual(cam['source_kind'], 'people_counter')
        self.assertIn('ISAPI_Smart_capabilities.xml', self.saved)
        self.assertIn('ISAPI_System_Video_inputs_channels_2_counting.xml', self.saved)


class DiagnosticsTests(unittest.TestCase):
    def test_export_zip_has_cameras_without_secrets(self):
        import json, zipfile
        from pathlib import Path
        from unittest.mock import patch
        from relleno import diagnostics
        config = {'binding': {'centre_id': 'eumachali', 'centre_name': 'Machali', 'agent_id': 'x'},
                  'cameras': [{'name': 'Acceso', 'ip': '10.0.0.1', 'model': 'DS-2CD6825', 'password': 'nope'}]}
        with tempfile.TemporaryDirectory() as root, patch.object(diagnostics, 'ROOT', Path(root)), \
                patch.object(diagnostics, 'load', return_value=config):
            (Path(root) / 'sources' / 'abc').mkdir(parents=True)
            (Path(root) / 'sources' / 'abc' / 'deviceInfo.xml').write_text('<x/>')
            target = diagnostics.export(Path(root) / 'out')
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                cams = json.loads(archive.read('camaras.json'))
        self.assertIn('fuentes/abc/deviceInfo.xml', names)
        self.assertNotIn('password', cams[0])
        self.assertEqual(cams[0]['model'], 'DS-2CD6825')
