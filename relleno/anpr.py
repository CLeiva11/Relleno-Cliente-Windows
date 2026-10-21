"""Durable outbox for the original HikCentral exports. No spreadsheet rewriting."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import uuid

import requests
from relleno.storage import ROOT, load, read_secret
from relleno.portal import BASE, endpoint, PortalError

EXTENSIONS = {'.xls', '.xlsx', '.xlsm'}


class AnprError(ValueError):
    pass


class Outbox:
    def __init__(self, root=None):
        self.root = Path(root) if root else ROOT / 'anpr'
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'outbox.sqlite3'
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS batches (
                batch_id TEXT PRIMARY KEY, centre_id TEXT NOT NULL, agent_id TEXT NOT NULL,
                sha256 TEXT NOT NULL, filename TEXT NOT NULL, source_path TEXT NOT NULL,
                spool_path TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                receipt_id TEXT, message TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
                UNIQUE (centre_id,sha256))''')
            db.execute('''CREATE TABLE IF NOT EXISTS export_jobs (
                job_key TEXT PRIMARY KEY, day TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
                message TEXT NOT NULL DEFAULT '')''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA synchronous=FULL')
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, source, binding):
        source = Path(source).resolve(strict=True)
        if source.suffix.lower() not in EXTENSIONS or not source.is_file():
            raise AnprError('Seleccione un XLS, XLSX o XLSM original exportado desde HikCentral.')
        before = source.stat()
        if before.st_size == 0 or before.st_size > 256 * 1024 * 1024:
            raise AnprError('El archivo está vacío o supera 256 MB. Exporte un intervalo más corto.')
        descriptor, temp_name = tempfile.mkstemp(dir=self.root, suffix='.tmp')
        temporary = Path(temp_name)
        digest = hashlib.sha256()
        try:
            with source.open('rb') as original, os.fdopen(descriptor, 'wb') as snapshot:
                signature = original.read(8)
                if not (signature.startswith(b'PK\x03\x04') or signature.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')):
                    raise AnprError('El archivo no tiene formato Excel. Use el archivo original de HikCentral.')
                snapshot.write(signature)
                digest.update(signature)
                for chunk in iter(lambda: original.read(1024 * 1024), b''):
                    snapshot.write(chunk)
                    digest.update(chunk)
                snapshot.flush()
                os.fsync(snapshot.fileno())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise AnprError('La exportación todavía está cambiando. Espere a que HikCentral termine.')
            sha = digest.hexdigest()
            batch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, str(binding['centre_id']) + '/anpr/' + sha))
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                existing = db.execute('SELECT batch_id FROM batches WHERE centre_id=? AND sha256=?', (str(binding['centre_id']), sha)).fetchone()
                if existing:
                    return existing['batch_id']
                folder = self.root / batch_id
                folder.mkdir(exist_ok=True)
                target = folder / ('source' + source.suffix.lower())
                temporary.replace(target)
                db.execute('''INSERT INTO batches
                    (batch_id,centre_id,agent_id,sha256,filename,source_path,spool_path,created)
                    VALUES (?,?,?,?,?,?,?,?)''',
                           (batch_id, str(binding['centre_id']), str(binding['agent_id']), sha,
                            source.name, str(source), str(target), time.time()))
            return batch_id
        finally:
            temporary.unlink(missing_ok=True)

    def list(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM batches ORDER BY created DESC')]

    def export_jobs(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute('SELECT * FROM export_jobs ORDER BY day DESC')]

    def update(self, batch_id, state, message, **values):
        allowed = {'receipt_id', 'next_attempt'}
        if set(values) - allowed:
            raise ValueError('Invalid queue update')
        columns = ['state=?', 'message=?'] + [key + '=?' for key in values]
        with self.connect() as db:
            db.execute('UPDATE batches SET ' + ','.join(columns) + ' WHERE batch_id=?',
                       [state, message, *values.values(), batch_id])

    @contextmanager
    def sender_lock(self, name='sender.lock'):
        import msvcrt
        with (self.root / name).open('a+b') as handle:
            if handle.tell() == 0:
                handle.write(b'0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise AnprError('Otro proceso está enviando ANPR. Espere a que termine.') from None
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def drain(self, config=None, session=None):
        config = config or load()
        binding = config.get('binding')
        if not binding:
            raise AnprError('Vincule primero este equipo con el centro.')
        secret = read_secret('portal/' + str(binding['agent_id']))
        if not secret or not secret.get('token'):
            raise AnprError('No se encontró el token del equipo en Windows.')
        url = endpoint(BASE, binding['upload_url'])
        if url == binding.get('people_count_url'):
            raise AnprError('El destino ANPR no puede ser el de Personas.')
        with self.sender_lock():
            # A previous process might have died after the server accepted a request.
            # Never blindly repeat that request without confirmed server idempotency.
            with self.connect() as db:
                db.execute("UPDATE batches SET state='uncertain',message='Envío interrumpido: revise Comprobaciones antes de reenviar.' WHERE state='sending'")
            owned = session is None
            session = session or requests.Session()
            try:
                for row in reversed(self.list()):
                    if row['state'] != 'pending' or row['next_attempt'] > time.time():
                        continue
                    if (row['centre_id'], row['agent_id']) != (str(binding['centre_id']), str(binding['agent_id'])):
                        continue
                    self.send(row, config, session, url, secret['token'])
            finally:
                if owned:
                    session.close()
        return self.list()

    def send(self, row, config, session, url, token):
        path = Path(row['spool_path'])
        if not path.is_file() or file_hash(path) != row['sha256']:
            self.update(row['batch_id'], 'blocked', 'La copia local no coincide con su SHA-256. No se envió.')
            return
        with self.connect() as db:
            db.execute("UPDATE batches SET state='sending',attempts=attempts+1 WHERE batch_id=? AND state='pending'", (row['batch_id'],))
        attempts = row['attempts'] + 1
        idempotent = config.get('anpr', {}).get('server_idempotency_confirmed', False)
        try:
            with path.open('rb') as handle:
                response = session.post(url, headers={'Authorization': 'Bearer ' + token,
                                                      'Idempotency-Key': row['batch_id']},
                                        files=[('source_files', (row['filename'], handle, mime_type(path)))],
                                        timeout=(10, 120), allow_redirects=False)
        except requests.ConnectTimeout:
            self.retry(row, attempts, 'No se pudo establecer conexión. Se reintentará.')
            return
        except requests.exceptions.SSLError:
            self.update(row['batch_id'], 'blocked', 'No se pudo verificar el certificado HTTPS del portal.')
            return
        except requests.RequestException:
            if idempotent:
                self.retry(row, attempts, 'Conexión interrumpida. Se reintentará con el mismo identificador.')
            else:
                self.update(row['batch_id'], 'uncertain', 'Conexión interrumpida: revise la recepción en Comprobaciones antes de reenviar.')
            return
        # Save the source response before recording a delivery. Never log its body.
        response_path = path.parent / ('response-' + str(attempts) + '.txt')
        response_path.write_text(response.text.replace(token, '[REDACTED]'), encoding='utf-8')
        try:
            data = response.json()
        except ValueError:
            data = None
        receipt = receipt_id(data)
        if 200 <= response.status_code < 300 and isinstance(data, dict) and data.get('ok') is True and receipt:
            self.update(row['batch_id'], 'delivered', 'Recibido por Comprobaciones', receipt_id=receipt)
        elif response.status_code >= 500 and idempotent:
            self.retry(row, attempts, f'Portal no disponible (HTTP {response.status_code}). Se reintentará.')
        elif response.status_code >= 500 or 200 <= response.status_code < 300:
            self.update(row['batch_id'], 'uncertain', f'HTTP {response.status_code}: recepción no confirmada por ID. Revise Comprobaciones.')
        else:
            self.update(row['batch_id'], 'blocked', f'Envío rechazado (HTTP {response.status_code}). Revise token, formato y permisos; no se reintentará automáticamente.')

    def retry(self, row, attempts, message):
        if attempts >= 8:
            self.update(row['batch_id'], 'blocked', 'Se agotaron los reintentos. Revise la conexión y Comprobaciones.')
        else:
            self.update(row['batch_id'], 'pending', message, next_attempt=time.time() + min(3600, 30 * 2 ** (attempts - 1)))


def receipt_id(data):
    if not isinstance(data, dict):
        return None
    for key in ('receipt_id', 'recepcion_id', 'reception_id', 'upload_id', 'import_id', 'batch_id', 'id'):
        value = data.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            return str(value)
    for key in ('receipt', 'recepcion', 'reception', 'upload', 'batch'):
        if isinstance(data.get(key), dict):
            value = receipt_id(data[key])
            if value:
                return value
    return None


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def mime_type(path):
    return {'.xls':'application/vnd.ms-excel', '.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xlsm':'application/vnd.ms-excel.sheet.macroEnabled.12'}[Path(path).suffix.lower()]
