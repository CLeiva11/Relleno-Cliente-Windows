"""Exporta un zip con lo que reporta cada cámara Hikvision, sin secretos."""
from datetime import datetime
from pathlib import Path
import json
import zipfile

from relleno.storage import ROOT, load


def export(destination=None):
    destination = Path(destination or Path.home() / 'Desktop')
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f'RellenoCliente-diagnostico-{datetime.now():%Y%m%d-%H%M%S}.zip'
    config = load()
    cameras = [
        {k: v for k, v in camera.items() if k in (
            'name', 'ip', 'external_id', 'model', 'firmware', 'source_kind', 'region',
            'region_id', 'channel_id', 'counting_enabled', 'connection_status', 'level', 'group')}
        for camera in config.get('cameras', [])
    ]
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('camaras.json', json.dumps(cameras, ensure_ascii=False, indent=2))
        archive.writestr('centro.json', json.dumps(
            {k: (config.get('binding') or {}).get(k) for k in ('centre_id', 'centre_name')}, ensure_ascii=False))
        sources = ROOT / 'sources'
        if sources.exists():
            for path in sources.rglob('*'):
                if path.is_file():
                    archive.write(path, Path('fuentes') / path.relative_to(sources))
        web = ROOT / 'diagnostics'
        if web.exists():
            for path in web.iterdir():
                if path.is_file():
                    archive.write(path, Path('hikcentral') / path.name)
    return target
