"""Exporta un zip con lo que reporta cada cámara Hikvision, sin secretos."""
from datetime import datetime
from pathlib import Path
import json
import platform
import shutil
import uuid
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
        failed_queries = sorted(
            (ROOT / 'batches').glob('*/source-*.xml') if (ROOT / 'batches').exists() else [],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )[:50]
        for path in failed_queries:
            archive.write(path, Path('consultas-personas') / path.parent.name / path.name)
    return target


def run_hikcentral(config, day):
    """Run the real HikCentral path without uploading ANPR, then package safe evidence."""
    from datetime import date
    from relleno.hcp_export import download
    from relleno.hikcentral import check
    from relleno.portal import CLIENT_VERSION
    from relleno.storage import read_secret

    selected_day = date.fromisoformat(str(day))
    run = ROOT / 'diagnostics' / ('remote-' + uuid.uuid4().hex[:12])
    run.mkdir(parents=True, exist_ok=False)
    successful = False
    message = 'Diagnóstico HikCentral completado.'
    evidence = {}
    try:
        settings = config.get('hikcentral') or {}
        credentials = read_secret('hikcentral')
        if not settings.get('url') or not credentials or credentials.get('method') != 'username':
            raise ValueError('HikCentral no tiene dirección y credenciales configuradas.')
        check(settings)
        source, evidence = download(config, selected_day, credentials, run, diagnostic_folder=run)
        source.unlink(missing_ok=True)
        successful = True
    except Exception as exc:
        message = str(exc)[:500] or 'El recorrido de HikCentral falló; se adjuntó evidencia.'
    finally:
        for pattern in ('*.xlsx', '*.xls', '*.xlsm'):
            for source in run.glob(pattern):
                source.unlink(missing_ok=True)

    summary = {
        'schema_version': 1,
        'client_version': CLIENT_VERSION,
        'centre_id': str((config.get('binding') or {}).get('centre_id') or ''),
        'day': selected_day.isoformat(),
        'successful': successful,
        'message': message,
        'platform': platform.platform(),
        'python': platform.python_version(),
        'adapter': evidence.get('adapter') if isinstance(evidence, dict) else None,
        'count': evidence.get('count') if isinstance(evidence, dict) else None,
    }
    (run / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    outgoing = ROOT / 'diagnostics' / 'outgoing'
    outgoing.mkdir(parents=True, exist_ok=True)
    target = outgoing / f'HikCentral-diagnostico-{selected_day}-{run.name[7:]}.zip'
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in run.rglob('*'):
            if path.is_file():
                archive.write(path, path.relative_to(run))
    shutil.rmtree(run, ignore_errors=True)
    return target, successful, message
