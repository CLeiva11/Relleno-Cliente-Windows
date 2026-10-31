import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from relleno import platform_support, storage


class ManjaroSupportTests(unittest.TestCase):
    @patch('relleno.platform_support.shutil.which')
    def test_system_chromium_is_used(self, which):
        which.side_effect = lambda name: '/usr/bin/chromium' if name == 'chromium' else None

        self.assertEqual(
            platform_support.browser_launch_kwargs(),
            {'executable_path': '/usr/bin/chromium', 'headless': False},
        )

    @patch('relleno.storage.IS_WINDOWS', False)
    @patch('relleno.storage.subprocess.run')
    def test_secrets_use_secret_service_without_plaintext_file(self, run):
        run.side_effect = [Mock(returncode=0, stdout=''), Mock(returncode=0, stdout='{"token":"safe"}\n')]

        storage.store_secret('portal/test', {'token': 'safe'})
        self.assertEqual(storage.read_secret('portal/test'), {'token': 'safe'})
        self.assertEqual(run.call_args_list[0].kwargs['input'], json.dumps({'token': 'safe'}, ensure_ascii=False))
        self.assertEqual(run.call_args_list[0].args[0][0], 'secret-tool')

    @patch('relleno.anpr_worker.IS_WINDOWS', False)
    @patch('relleno.anpr_worker.worker_command', return_value=['/opt/RellenoCliente', '--agent-worker'])
    def test_linux_autostart_is_xdg_desktop_entry(self, command):
        from relleno.anpr_worker import autostart
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'XDG_CONFIG_HOME': folder}):
            autostart(True)
            target = Path(folder) / 'autostart' / 'relleno-cliente.desktop'
            self.assertIn('Exec="/opt/RellenoCliente" "--agent-worker"', target.read_text(encoding='utf-8'))
            autostart(False)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
