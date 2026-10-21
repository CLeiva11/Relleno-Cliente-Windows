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
        self.assertEqual(capabilities(config), ['personas', 'vehiculos'])

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

    @patch('relleno.agent.generate_anpr', return_value=['receipt-anpr'])
    def test_vehicle_command_reuses_anpr_pipeline(self, generate):
        config = {'binding': {'centre_id': 'centre'}}
        command = {'data_type': 'vehiculos', 'day': '2026-10-20'}
        self.assertEqual(execute_command(config, command, Mock()), ['receipt-anpr'])


if __name__ == '__main__':
    unittest.main()
