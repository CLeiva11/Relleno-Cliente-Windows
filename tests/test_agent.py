import unittest
from unittest.mock import Mock, patch

from relleno.agent import capabilities, execute_command, generate_people


class AgentTests(unittest.TestCase):
    @patch('relleno.agent.read_secret')
    def test_capabilities_follow_configured_extractors(self, secret):
        secret.return_value = {'method': 'username'}
        config = {
            'hikcentral': {'url': 'https://hikcentral.test'},
            'cameras': [
                {'source_kind': 'people_counter', 'counting_enabled': True},
                {'source_kind': 'rf_counter', 'counting_enabled': True},
            ],
        }
        self.assertEqual(capabilities(config), ['personas', 'vehiculos', 'diagnostico'])

    @patch('relleno.agent.send_batch', return_value='receipt-1')
    @patch('relleno.agent.extract_day', return_value={'batch_id': 'batch-1'})
    def test_people_command_extracts_and_delivers_each_supported_camera(self, extract, send):
        config = {
            'binding': {'centre_id': 'centre'}, 'timezone': 'America/Santiago',
            'cameras': [{'name': 'Acceso', 'source_kind': 'people_counter', 'counting_enabled': True}],
        }
        self.assertEqual(generate_people(config, '2026-10-20'), ['receipt-1'])
        extract.assert_called_once()
        send.assert_called_once_with(config['binding'], {'batch_id': 'batch-1'})

    @patch('relleno.agent.save')
    @patch('relleno.agent.probe')
    @patch('relleno.agent.send_batch', return_value='receipt-1')
    @patch('relleno.agent.extract_day', return_value={'batch_id': 'batch-1'})
    def test_people_command_reprobes_pending_camera_without_opening_ui(self, extract, send, probe, save):
        pending = {'name': 'Castaño', 'model': '', 'source_kind': 'pending'}
        detected = dict(pending, model='DS-2CD6825G0/C-IVS', source_kind='people_counter', counting_enabled=True)
        probe.return_value = detected
        config = {'binding': {'centre_id': 'centre'}, 'timezone': 'America/Santiago', 'cameras': [pending]}

        self.assertEqual(generate_people(config, '2026-10-20'), ['receipt-1'])

        probe.assert_called_once_with(pending)
        save.assert_called_once_with(config)
        extract.assert_called_once_with(detected, '2026-10-20', 'America/Santiago', 'centre')

    @patch('relleno.agent.save')
    @patch('relleno.agent.send_batch', return_value='receipt-1')
    @patch('relleno.agent.extract_day')
    def test_people_command_persists_certificate_pinned_during_extraction(self, extract, send, save):
        camera = {
            'external_id': '101', 'ip': '192.168.1.101', 'name': 'Acceso',
            'source_kind': 'people_counter', 'counting_enabled': True,
        }
        config = {
            'binding': {'centre_id': 'centre'}, 'timezone': 'America/Santiago',
            'cameras': [camera],
        }

        def pin_certificate(current, *_args):
            current['https_fingerprint'] = 'abc123'
            return {'batch_id': 'batch-1'}

        extract.side_effect = pin_certificate

        self.assertEqual(generate_people(config, '2026-10-20'), ['receipt-1'])
        save.assert_called_once_with(config)
        self.assertEqual(config['cameras'][0]['https_fingerprint'], 'abc123')

    @patch('relleno.agent.generate_anpr', return_value=['receipt-anpr'])
    def test_vehicle_command_reuses_anpr_pipeline(self, generate):
        config = {'binding': {'centre_id': 'centre'}}
        command = {'data_type': 'vehiculos', 'day': '2026-10-20'}
        self.assertEqual(execute_command(config, command, Mock()), ['receipt-anpr'])

    @patch('relleno.agent.upload_diagnostic', return_value='diagnostic-1')
    @patch('relleno.diagnostics.run_hikcentral')
    def test_diagnostic_command_uploads_and_removes_archive(self, run, upload):
        archive = Mock()
        run.return_value = (archive, True, 'Diagnóstico completado')
        config = {'binding': {'centre_id': 'centre'}}
        command = {'id': 'command-1', 'data_type': 'diagnostico', 'day': '2026-10-20'}

        result = execute_command(config, command, Mock())

        self.assertEqual(result['diagnostic_id'], 'diagnostic-1')
        upload.assert_called_once_with(config['binding'], archive, 'command-1')
        archive.unlink.assert_called_once_with(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
