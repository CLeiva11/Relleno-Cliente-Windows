import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from relleno.alarms import AlarmScheduler, commands, installation, month_ranges, run_now


class AlarmTests(unittest.TestCase):
    def configured(self, root):
        root = Path(root)
        (root / 'config_centro.json').write_text('{}', encoding='utf-8')
        (root / 'fetch_alarmas_hikcentral.py').write_text('', encoding='utf-8')
        (root / 'fetch_alarmas_ivms_injection.py').write_text('', encoding='utf-8')
        python = root / 'python.exe'
        python.write_text('', encoding='utf-8')
        (root / 'EJECUTAR_SYNC_DIARIA_GENERADO.cmd').write_text(
            f'"{python}" "{root / "orquestador_diario.py"}" --config x', encoding='utf-8'
        )
        return {'alarms': {'enabled': True, 'sync_dir': str(root), 'run_hour': 3}}

    def test_installation_requires_config_orchestrator_and_generated_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            config = {'alarms': {'sync_dir': directory}}
            self.assertFalse(installation(config)['ready'])
            self.configured(directory)
            self.assertTrue(installation(config)['ready'])

    def test_successful_run_records_completed_day(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.configured(directory)
            process = Mock(returncode=0, stdout='', stderr='')
            with patch('relleno.alarms.STATE_FILE', Path(directory) / 'state.json'):
                state = run_now(config, run=Mock(return_value=process), now=datetime(2026, 11, 2, 3, 0))
            self.assertEqual(state['state'], 'completed')
            self.assertEqual(state['completed_day'], '2026-11-02')

    def test_commands_use_hikcentral_and_ivms_injection_with_month_split(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.configured(directory)
            selected = commands(config, datetime(2026, 11, 2, 3, 0))
            self.assertIn('fetch_alarmas_hikcentral.py', selected[0][1])
            self.assertIn('fetch_alarmas_ivms_injection.py', selected[1][1])
            self.assertEqual(selected[1][-3:], ['2026-10-30', '--to-date', '2026-10-31'])
            self.assertEqual(selected[2][-3:], ['2026-11-01', '--to-date', '2026-11-01'])

    def test_scheduler_runs_only_once_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.configured(directory)
            state_file = Path(directory) / 'state.json'
            state_file.write_text(json.dumps({'completed_day': '2026-11-02'}), encoding='utf-8')
            scheduler = AlarmScheduler()
            scheduler.tasks_disabled = True
            with patch('relleno.alarms.STATE_FILE', state_file), patch('relleno.alarms.run_now') as execute:
                scheduler.tick(config, now=datetime(2026, 11, 2, 4, 0))
            execute.assert_not_called()

    def test_scheduler_does_not_block_agent_loop(self):
        with tempfile.TemporaryDirectory() as directory:
            config = self.configured(directory)
            scheduler = AlarmScheduler()
            scheduler.tasks_disabled = True
            with patch('relleno.alarms.STATE_FILE', Path(directory) / 'state.json'), \
                    patch.object(scheduler, '_run_safely') as execute:
                scheduler.tick(config, now=datetime(2026, 11, 2, 4, 0))
                scheduler.worker.join(timeout=1)
            execute.assert_called_once()


if __name__ == '__main__':
    unittest.main()
