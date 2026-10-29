from pathlib import Path
import hashlib
import tempfile
import unittest
from unittest.mock import Mock, patch

from relleno.portal import PortalError
from relleno.updater import available, download, version_tuple


class UpdaterTests(unittest.TestCase):
    def test_versions_are_numeric_and_downgrades_are_ignored(self):
        self.assertGreater(version_tuple('0.4.29'), version_tuple('0.4.9'))
        with patch('relleno.updater.agent_post', return_value={
            'update': {'version':'0.4.28', 'filename':'RellenoCliente-Setup-0.4.28.exe',
                       'sha256':'a'*64, 'size':2048}
        }):
            self.assertIsNone(available({}))
        with self.assertRaises(PortalError):
            version_tuple('latest')

    @patch('relleno.updater.agent_token', return_value='token')
    @patch('relleno.updater.binding_endpoint', return_value='https://portal/update.exe')
    @patch('relleno.updater.requests.get')
    def test_download_requires_exact_size_hash_and_mz(self, get, endpoint, token):
        payload = b'MZ' + b'x' * 2046
        response = Mock()
        response.status_code = 200
        response.iter_content.return_value = [payload]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        get.return_value = response
        metadata = {
            'version':'0.4.30', 'filename':'RellenoCliente-Setup-0.4.30.exe',
            'sha256':hashlib.sha256(payload).hexdigest(), 'size':len(payload),
        }
        with tempfile.TemporaryDirectory() as temporary, patch('relleno.updater.ROOT', Path(temporary)):
            target = download({}, metadata)
            self.assertEqual(target.read_bytes(), payload)

    @patch('relleno.updater.agent_token', return_value='token')
    @patch('relleno.updater.binding_endpoint', return_value='https://portal/update.exe')
    @patch('relleno.updater.requests.get')
    def test_download_rejects_tampered_payload(self, get, endpoint, token):
        response = Mock()
        response.status_code = 200
        response.iter_content.return_value = [b'MZ' + b'x' * 2046]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        get.return_value = response
        metadata = {
            'version':'0.4.30', 'filename':'RellenoCliente-Setup-0.4.30.exe',
            'sha256':'0'*64, 'size':2048,
        }
        with tempfile.TemporaryDirectory() as temporary, patch('relleno.updater.ROOT', Path(temporary)):
            with self.assertRaisesRegex(PortalError, 'SHA-256'):
                download({}, metadata)
