import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo

ROOT = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'RellenoCliente'


def load():
    path = ROOT / 'config.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'cameras': [], 'timezone': 'America/Santiago', 'period_minutes': 60}


def save(config):
    ROOT.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=ROOT, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(config, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, ROOT / 'config.json')
    finally:
        if os.path.exists(name):
            os.unlink(name)


def validate_camera(camera, cameras, previous=None):
    for key in ('external_id', 'name', 'ip', 'direction', 'source_kind'):
        if not camera.get(key, '').strip():
            raise ValueError('Complete ID, nombre, dirección de red, dirección y tipo.')
    if camera['source_kind'] not in ('people_counter', 'rf_counter', 'anpr'):
        raise ValueError('Tipo de cámara inválido.')
    if any(c['external_id'] == camera['external_id'] and c['external_id'] != previous for c in cameras):
        raise ValueError('Ya existe una cámara con ese ID.')


class Credential(ctypes.Structure):
    _fields_ = [('Flags', wintypes.DWORD), ('Type', wintypes.DWORD),
                ('TargetName', wintypes.LPWSTR), ('Comment', wintypes.LPWSTR),
                ('LastWritten', wintypes.FILETIME), ('CredentialBlobSize', wintypes.DWORD),
                ('CredentialBlob', ctypes.POINTER(ctypes.c_ubyte)),
                ('Persist', wintypes.DWORD), ('AttributeCount', wintypes.DWORD),
                ('Attributes', ctypes.c_void_p), ('TargetAlias', wintypes.LPWSTR),
                ('UserName', wintypes.LPWSTR)]


def store_secret(target, values):
    """Use Windows Credential Manager; never fall back to a file."""
    blob = json.dumps(values, ensure_ascii=False).encode('utf-16-le')
    if len(blob) > 2560:
        raise ValueError('Credencial demasiado larga.')
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = Credential(Type=1, TargetName='RellenoCliente/' + target,
                      CredentialBlobSize=len(blob), CredentialBlob=buffer,
                      Persist=2, UserName='RellenoCliente')
    api = ctypes.WinDLL('Advapi32', use_last_error=True)
    api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    if not api.CredWriteW(ctypes.byref(cred), 0):
        raise OSError('Windows no pudo guardar la credencial de forma segura.')


def read_secret(target):
    api = ctypes.WinDLL('Advapi32', use_last_error=True)
    pointer = ctypes.POINTER(Credential)()
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    if not api.CredReadW('RellenoCliente/' + target, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise OSError('Windows no pudo leer la credencial segura.')
    try:
        value = pointer.contents
        return json.loads(ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize).decode('utf-16-le'))
    finally:
        api.CredFree(pointer)
