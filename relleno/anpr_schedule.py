import time
from relleno.anpr import Outbox
from relleno.hcp_export import export_day, export_key, pending_days, ExportError


BLOCKED_RETRY_SECONDS = 6 * 60 * 60
PUENTE_ALTO_BACKFILL = ('2026-10-01', '2026-11-01')


def apply_required_backfill(config, outbox) -> bool:
    """Schedule the requested Puente Alto recovery once without resending successes."""
    binding = config.get('binding') or {}
    if binding.get('centre_id') != 'eupuentealto':
        return False
    marker = 'eupuentealto-vehiculos-2026-10-01_2026-11-01-v1'
    settings = config.setdefault('anpr', {})
    if settings.get('required_backfill') == marker:
        return False
    current = settings.get('export_since')
    settings['export_since'] = min(current, PUENTE_ALTO_BACKFILL[0]) if current else PUENTE_ALTO_BACKFILL[0]
    settings['auto_export_enabled'] = True
    settings['required_backfill'] = marker
    with outbox.connect() as db:
        db.execute(
            "UPDATE export_jobs SET state='pending',attempts=0,next_attempt=0,message=? "
            "WHERE day BETWEEN ? AND ? AND state IN ('blocked','exporting')",
            ('Recuperación solicitada para octubre y 1 de noviembre', *PUENTE_ALTO_BACKFILL),
        )
    return True


def export_and_enqueue(config, day, box=None):
    box = box or Outbox()
    from datetime import date
    if isinstance(day, str):
        day = date.fromisoformat(day)
    source = export_day(config, day)
    batch = box.add(source, config['binding'])
    key = export_key(config, day)
    with box.connect() as db:
        db.execute("INSERT INTO export_jobs(job_key,day,state,message) VALUES (?,?,'exported','Excel original descargado y conservado en la cola') ON CONFLICT(job_key) DO UPDATE SET state='exported',message=excluded.message",
                   (key, day.isoformat()))
    return batch


class Scheduler:
    def __init__(self, outbox=None):
        self.outbox = outbox or Outbox()
        with self.outbox.connect() as db:
            db.execute("UPDATE export_jobs SET state='pending',message='Ventana recuperada después de reinicio' WHERE state='exporting'")

    def tick(self, config):
        if not config.get('anpr', {}).get('auto_export_enabled') or not config.get('binding'):
            return
        days = pending_days(config)
        with self.outbox.connect() as db:
            for day in days:
                db.execute('INSERT OR IGNORE INTO export_jobs(job_key,day) VALUES (?,?)', (export_key(config, day), day.isoformat()))
        jobs = {job['job_key']:job for job in self.outbox.export_jobs()}
        for day in days:
            key = export_key(config, day)
            job = jobs[key]
            if job['state'] == 'blocked' and job['next_attempt'] <= time.time():
                with self.outbox.connect() as db:
                    db.execute(
                        "UPDATE export_jobs SET state='pending',attempts=0,message=? WHERE job_key=?",
                        ('Reintentando exportación bloqueada después del período de espera', key),
                    )
                job = dict(job, state='pending', attempts=0)
            if job['state'] != 'pending' or job['next_attempt'] > time.time():
                continue
            with self.outbox.connect() as db:
                db.execute("UPDATE export_jobs SET state='exporting',attempts=attempts+1 WHERE job_key=?", (key,))
            try:
                export_and_enqueue(config, day, self.outbox)
            except Exception as exc:
                message = str(exc) if isinstance(exc, ExportError) else 'No se completó la exportación. Revise HikCentral desde la aplicación.'
                attempts = job['attempts'] + 1
                blocked = attempts >= 3 or 'inicio de sesión' in message
                next_attempt = (
                    time.time() + BLOCKED_RETRY_SECONDS
                    if blocked else time.time() + min(3600, 300*2**(attempts-1))
                )
                with self.outbox.connect() as db:
                    db.execute('UPDATE export_jobs SET state=?,next_attempt=?,message=? WHERE job_key=?',
                               ('blocked' if blocked else 'pending', next_attempt, message, key))
            break  # Process one window per cycle; pending windows survive restarts.
