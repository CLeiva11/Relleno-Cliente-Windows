"""Send new, completed HikCentral exports without opening a development console."""
import fnmatch
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import subprocess
import sys
import time

from relleno.storage import ROOT, load
from relleno.anpr import Outbox, EXTENSIONS, AnprError


def logger():
    log = logging.getLogger('relleno.anpr')
    if not log.handlers:
        folder = ROOT / 'logs'
        folder.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(folder / 'anpr.log', maxBytes=1024*1024, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    return log


class Watcher:
    def __init__(self, outbox=None):
        self.outbox = outbox or Outbox()
        self.observed = {}
        self.enqueued = {}

    def scan(self, config):
        settings = config.get('anpr', {})
        if not settings.get('watch_enabled') or not config.get('binding'):
            return []
        folder = Path(settings['watch_folder'])
        if not folder.is_dir():
            raise AnprError('La carpeta de exportaciones no está disponible.')
        added = []
        for path in folder.iterdir():
            if path.suffix.lower() not in EXTENSIONS or not fnmatch.fnmatchcase(path.name.casefold(), settings.get('file_pattern', '*ANPR*').casefold()):
                continue
            stat = path.stat()
            if stat.st_mtime_ns < settings.get('watch_since_ns', 0) or time.time() - stat.st_mtime < 15:
                continue
            signature = (stat.st_size, stat.st_mtime_ns)
            previous = self.observed.get(str(path))
            self.observed[str(path)] = signature
            if previous != signature:
                continue
            if self.enqueued.get(str(path)) == signature:
                continue
            batch = self.outbox.add(path, config['binding'])
            self.enqueued[str(path)] = signature
            added.append(batch)
        return added


def run():
    box = Outbox()
    log = logger()
    try:
        with box.sender_lock('worker.lock'):
            watcher = Watcher(box)
            from relleno.anpr_schedule import Scheduler
            scheduler = Scheduler(box)
            from relleno.people_schedule import PeopleScheduler
            people_scheduler = PeopleScheduler(box)
            log.info('Servicio de Comprobaciones iniciado')
            last_heartbeat = 0
            while True:
                config = load()
                if not config.get('binding'):
                    log.info('Servicio sin vinculación')
                    return
                try:
                    watcher.scan(config)
                    scheduler.tick(config)
                    people_scheduler.tick(config)
                    box.drain(config)
                    from relleno.agent import heartbeat, poll_command, execute_command, complete_command
                    if time.time() - last_heartbeat >= 60:
                        heartbeat(config)
                        last_heartbeat = time.time()
                    command = poll_command(config)
                    if command:
                        try:
                            result = execute_command(config, command, box)
                            if isinstance(result, dict) and result.get('diagnostic_id'):
                                complete_command(
                                    config, command, 'completed' if result.get('successful') else 'failed',
                                    result.get('message') or 'Diagnóstico recibido',
                                    diagnostic_id=result['diagnostic_id'],
                                )
                            else:
                                complete_command(config, command, 'completed', 'Generación recibida por Comprobaciones', result)
                        except Exception as exc:
                            complete_command(config, command, 'failed', str(exc)[:500])
                except Exception:
                    # No exception text, URLs, headers or server bodies enter logs.
                    log.warning('Revisión del servicio pendiente; consulte la aplicación')
                time.sleep(15)
    except AnprError:
        return  # Another monitor owns the operating system lock.


def autostart(enabled):
    if not getattr(sys, 'frozen', False):
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            winreg.SetValueEx(key, 'RellenoClienteServicio', 0, winreg.REG_SZ, '"' + sys.executable + '" --agent-worker')
            try:
                winreg.DeleteValue(key, 'RellenoClienteANPR')
            except FileNotFoundError:
                pass
        else:
            for name in ('RellenoClienteServicio', 'RellenoClienteANPR'):
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass


def start():
    if getattr(sys, 'frozen', False):
        command = [sys.executable, '--agent-worker']
    else:
        command = [sys.executable, str(Path(__file__).resolve().parent.parent / 'main.py'), '--agent-worker']
    subprocess.Popen(command, creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
