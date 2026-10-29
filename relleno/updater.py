"""Authenticated, fail-closed updates distributed by the Relleno portal."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys

import requests

from relleno.portal import CLIENT_VERSION, PortalError, agent_post, agent_token, binding_endpoint
from relleno.storage import ROOT


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
MAX_BYTES = 250 * 1024 * 1024
CHECK_INTERVAL = 6 * 60 * 60


def version_tuple(value):
    value = str(value or "").strip()
    if not VERSION_RE.fullmatch(value):
        raise PortalError("El portal publicó una versión con formato inválido.")
    return tuple(int(part) for part in value.split("."))


def available(binding):
    payload = agent_post(binding, 'update_check_url', {'client_version': CLIENT_VERSION})
    metadata = payload.get('update')
    if not metadata:
        return None
    if version_tuple(metadata.get('version')) <= version_tuple(CLIENT_VERSION):
        return None
    digest = str(metadata.get('sha256') or '').lower()
    size = int(metadata.get('size') or 0)
    filename = str(metadata.get('filename') or '')
    if not re.fullmatch(r'RellenoCliente-Setup-\d+\.\d+\.\d+\.exe', filename):
        raise PortalError('El portal publicó un nombre de instalador inválido.')
    if not re.fullmatch(r'[a-f0-9]{64}', digest) or not 1024 <= size <= MAX_BYTES:
        raise PortalError('El portal publicó metadatos de actualización inválidos.')
    return dict(metadata, sha256=digest, size=size, filename=filename)


def download(binding, metadata):
    folder = ROOT / 'updates'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / metadata['filename']
    temporary = target.with_suffix('.exe.part')
    digest = hashlib.sha256()
    received = 0
    try:
        with requests.get(
            binding_endpoint(binding, 'update_download_url'),
            headers={'Authorization': 'Bearer ' + agent_token(binding)},
            stream=True, timeout=(10, 300), allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise PortalError(f'El portal rechazó la actualización (HTTP {response.status_code}).')
            with temporary.open('wb') as handle:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    received += len(chunk)
                    if received > metadata['size'] or received > MAX_BYTES:
                        raise PortalError('La actualización supera el tamaño publicado.')
                    digest.update(chunk)
                    handle.write(chunk)
        if received != metadata['size'] or digest.hexdigest() != metadata['sha256']:
            raise PortalError('La actualización no coincide con su SHA-256 publicado.')
        with temporary.open('rb') as handle:
            if handle.read(2) != b'MZ':
                raise PortalError('La actualización no es un ejecutable de Windows válido.')
        temporary.replace(target)
        return target
    except (OSError, requests.RequestException):
        raise PortalError('No se pudo descargar la actualización del portal.') from None
    finally:
        temporary.unlink(missing_ok=True)


def check_and_install(config):
    if not getattr(sys, 'frozen', False) or not config.get('binding'):
        return False
    metadata = available(config['binding'])
    if not metadata:
        return False
    installer = download(config['binding'], metadata)
    subprocess.Popen(
        [str(installer), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS'],
        creationflags=subprocess.CREATE_NO_WINDOW,
        close_fds=True,
    )
    return True
