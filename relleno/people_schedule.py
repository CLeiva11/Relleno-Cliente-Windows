"""Durable daily schedule for camera-by-camera people extraction."""
from datetime import date, datetime, timedelta
import hashlib
import time
from zoneinfo import ZoneInfo


def job_key(config, day):
    value = f"{config['binding']['centre_id']}/personas/{day.isoformat()}"
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def pending_days(config, now=None):
    zone = ZoneInfo(config.get('timezone', 'America/Santiago'))
    now = now.astimezone(zone) if now is not None else datetime.now(zone)
    last = now.date() - timedelta(days=1 if now.hour >= 1 else 2)
    first = date.fromisoformat(config.get('people', {}).get('export_since', last.isoformat()))
    return [first + timedelta(days=index) for index in range(max(0, (last - first).days + 1))]


class PeopleScheduler:
    def __init__(self, outbox):
        self.outbox = outbox
        with self.outbox.connect() as db:
            db.execute("UPDATE people_jobs SET state='pending',message='Ventana recuperada después de reinicio' WHERE state='extracting'")

    def tick(self, config):
        if not config.get('people', {}).get('auto_export_enabled') or not config.get('binding'):
            return
        days = pending_days(config)
        with self.outbox.connect() as db:
            for day in days:
                db.execute('INSERT OR IGNORE INTO people_jobs(job_key,day) VALUES (?,?)', (job_key(config, day), day.isoformat()))
        jobs = {item['job_key']: item for item in self.outbox.people_jobs()}
        for day in days:
            key = job_key(config, day)
            job = jobs[key]
            if job['state'] != 'pending' or job['next_attempt'] > time.time():
                continue
            with self.outbox.connect() as db:
                db.execute("UPDATE people_jobs SET state='extracting',attempts=attempts+1 WHERE job_key=?", (key,))
            try:
                from relleno.agent import generate_people
                receipts = generate_people(config, day.isoformat())
                with self.outbox.connect() as db:
                    db.execute("UPDATE people_jobs SET state='delivered',message=? WHERE job_key=?",
                               (f'{len(receipts)} cámara(s) recibidas por Comprobaciones', key))
            except Exception as exc:
                attempts = job['attempts'] + 1
                blocked = attempts >= 3
                with self.outbox.connect() as db:
                    db.execute('UPDATE people_jobs SET state=?,next_attempt=?,message=? WHERE job_key=?',
                               ('blocked' if blocked else 'pending', time.time() + min(3600, 300 * 2 ** (attempts - 1)), str(exc)[:500], key))
            break
