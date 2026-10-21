import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from relleno import storage
from relleno.portal import binding_endpoint, endpoint, link, BASE


class CoreTests(unittest.TestCase):
    def test_endpoint_stays_on_portal(self):
        self.assertEqual(endpoint(BASE, '/api/upload/'), 'https://siem.domoticatechnology.cl/relleno/api/upload/')
        self.assertEqual(endpoint(BASE, '/relleno/api/upload/'), 'https://siem.domoticatechnology.cl/relleno/api/upload/')
        for value in ('http://external.test/x', 'https://external.test/x', '//external.test/x', 'https://u:p@siem.domoticatechnology.cl/x'):
            with self.assertRaises(ValueError):
                endpoint(BASE, value)

    def test_existing_binding_gets_current_service_endpoints(self):
        binding = {'agent_id': 'a'}
        self.assertEqual(
            binding_endpoint(binding, 'commands_url'),
            BASE + '/api/comprobaciones/agentes/ordenes/',
        )

    def test_inventory_and_atomic_save(self):
        camera = dict(external_id='test', name='Prueba', ip='camera.invalid', direction='bidirectional', source_kind='rf_counter')
        storage.validate_camera(camera, [])
        with self.assertRaises(ValueError):
            storage.validate_camera(camera, [camera])
        with tempfile.TemporaryDirectory() as folder, patch.object(storage, 'ROOT', Path(folder)):
            config = {'cameras': [camera], 'timezone': 'America/Santiago', 'period_minutes': 60}
            storage.save(config)
            self.assertEqual(storage.load(), config)
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    @patch('relleno.storage.store_secret')
    @patch('relleno.portal.requests.post')
    def test_no_people_channel_is_added(self, post, secret):
        post.return_value.status_code = 200
        post.return_value.json.return_value = dict(ok=True, agent_id='a', agent_token='test-only', centre_id='c', centre_name='Prueba', upload_url='/api/anpr/')
        self.assertNotIn('people_count_url', link('test-only', 'test'))
        self.assertFalse(post.call_args.kwargs['allow_redirects'])
        secret.assert_called_once()

    @patch('relleno.portal.requests.post')
    def test_expired_code_has_actionable_message(self, post):
        from relleno.portal import PortalError
        post.return_value.status_code = 401
        with self.assertRaisesRegex(PortalError, 'Genere uno nuevo'):
            link('test-only', 'test')

    @patch('relleno.storage.store_secret')
    @patch('relleno.portal.requests.post')
    def test_created_status_and_prefix(self, post, secret):
        post.return_value.status_code = 201
        post.return_value.json.return_value = dict(ok=True, agent_id='a', agent_token='test-only', centre_id='c', centre_name='Prueba', upload_url='/api/anpr/')
        self.assertEqual(link(' test-only ', 'test')['upload_url'], BASE + '/api/anpr/')
        self.assertEqual(post.call_args.kwargs['json']['code'], 'TEST-ONLY')

    @patch('relleno.portal.requests.post')
    def test_no_raw_response_is_exposed(self, post):
        from relleno.portal import PortalError
        post.return_value.status_code = 500
        post.return_value.text = 'sensitive response'
        with self.assertRaises(PortalError) as caught:
            link('test-only', 'test')
        self.assertNotIn('sensitive', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
