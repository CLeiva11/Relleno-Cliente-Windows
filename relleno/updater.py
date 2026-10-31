"""Authenticated, fail-closed updates distributed by the Relleno portal."""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tarfile

import requests

from relleno.portal import CLIENT_VERSION, PortalError, agent_post, agent_token, binding_endpoint
from relleno.storage import ROOT
from relleno.platform_support import IS_WINDOWS, detached_process_kwargs


VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
MAX_BYTES = 250 * 1024 * 1024
CHECK_INTERVAL = 6 * 60 * 60


def version_tuple(value):
    value = str(value or "").strip()
    if not VERSION_RE.fullmatch(value):
        raise PortalError("El portal publicó una versión con formato inválido.")
    return tuple(int(part) for part in value.split("."))


def available(binding):
    platform_name = 'windows' if IS_WINDOWS else 'manjaro'
    payload = agent_post(binding, 'update_check_url', {
        'client_version': CLIENT_VERSION,
        'client_platform': platform_name,
    })
    metadata = payload.get('update')
    if not metadata:
        return None
    if version_tuple(metadata.get('version')) <= version_tuple(CLIENT_VERSION):
        return None
    digest = str(metadata.get('sha256') or '').lower()
    size = int(metadata.get('size') or 0)
    filename = str(metadata.get('filename') or '')
    pattern = (
        r'RellenoCliente-Setup-\d+\.\d+\.\d+\.exe'
        if IS_WINDOWS else r'RellenoCliente-Manjaro-\d+\.\d+\.\d+\.tar\.gz'
    )
    if not re.fullmatch(pattern, filename):
        # A portal that still publishes only Windows releases must not offer
        # that executable to a Manjaro workstation.
        if not IS_WINDOWS and filename.endswith('.exe'):
            return None
        raise PortalError('El portal publicó un nombre de instalador inválido.')
    if not re.fullmatch(r'[a-f0-9]{64}', digest) or not 1024 <= size <= MAX_BYTES:
        raise PortalError('El portal publicó metadatos de actualización inválidos.')
    return dict(metadata, sha256=digest, size=size, filename=filename)


def download(binding, metadata):
    folder = ROOT / 'updates'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / metadata['filename']
    temporary = target.with_name(target.name + '.part')
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
            signature = handle.read(2)
            if IS_WINDOWS and signature != b'MZ':
                raise PortalError('La actualización no es un ejecutable de Windows válido.')
            if not IS_WINDOWS and signature != b'\x1f\x8b':
                raise PortalError('La actualización no es un paquete válido para Manjaro.')
        temporary.replace(target)
        return target
    except (OSError, requests.RequestException):
        raise PortalError('No se pudo descargar la actualización del portal.') from None
    finally:
        temporary.unlink(missing_ok=True)


def launch(installer):
    """Start verified Setup with visible progress and a local diagnostic log."""
    if not IS_WINDOWS:
        target = ROOT / 'updates' / ('unpacked-' + installer.name.removesuffix('.tar.gz'))
        target.mkdir(parents=True, exist_ok=True)
        try:
            with tarfile.open(installer, 'r:gz') as archive:
                archive.extractall(target, filter='data')
        except (OSError, tarfile.TarError):
            raise PortalError('No se pudo abrir el paquete verificado para Manjaro.') from None
        script = target / 'install-manjaro.sh'
        if not script.is_file():
            raise PortalError('El paquete para Manjaro no incluye su instalador.')
        return subprocess.Popen(['bash', str(script), '--update'], **detached_process_kwargs())
    log_path = ROOT / 'updates' / 'installer.log'
    return subprocess.Popen(
        [
            str(installer), '/SILENT', '/SUPPRESSMSGBOXES', '/NORESTART',
            '/CLOSEAPPLICATIONS', '/LOG=' + str(log_path),
        ],
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        close_fds=True,
    )


def check_and_install(config):
    if not getattr(sys, 'frozen', False) or not config.get('binding'):
        return False
    metadata = available(config['binding'])
    if not metadata:
        return False
    installer = download(config['binding'], metadata)
    launch(installer)
    return True
