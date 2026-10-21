"""Read-only ISAPI adapter, based on the requests used by the camera web portal."""
from datetime import date, datetime, timedelta, timezone
import hashlib
import ipaddress
import json
import re
import uuid
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

import requests
from requests.auth import HTTPDigestAuth
from relleno.storage import ROOT, read_secret, store_secret


class CameraError(ValueError):
    pass


def host_url(host):
    host = host.strip().rstrip('\\/')
    try:
        ip = ipaddress.ip_address(host)
        return 'http://' + ('[' + host + ']' if ip.version == 6 else host)
    except ValueError:
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', host):
            raise CameraError('Ingrese una IP o nombre de cámara sin usuario, ruta ni contraseña.')
        return 'http://' + host


def xml_tree(content):
    try:
        tree = ET.fromstring(content)
    except ET.ParseError:
        raise CameraError('La cámara devolvió una respuesta inválida.') from None
    for node in tree.iter():
        node.tag = node.tag.split('}')[-1]
    return tree


def request(camera, path, body=None):
    secret = read_secret('camera/' + camera['external_id']) or read_secret('camera-default')
    if not secret:
        raise CameraError('Guarde primero el usuario y la contraseña de las cámaras.')
    try:
        response = requests.request('POST' if body else 'GET', host_url(camera['ip']) + path,
                                    auth=HTTPDigestAuth(secret['username'], secret['password']),
                                    data=body, headers={'Content-Type': 'application/xml'},
                                    timeout=(5, 20), allow_redirects=False)
    except requests.RequestException:
        raise CameraError('No se pudo conectar con la cámara.') from None
    if response.status_code == 401:
        raise CameraError('La cámara rechazó el usuario o la contraseña. No se reintentó.')
    if response.status_code != 200:
        raise CameraError(f'La cámara respondió HTTP {response.status_code}.')
    return response.content


# Consultas ISAPI de solo lectura que describen lo que soporta cada Hikvision.
# Se guardan para diagnosticar modelos nuevos (conteo, RF/rostros) sin adivinar.
CAPABILITY_PATHS = (
    '/ISAPI/System/capabilities',
    '/ISAPI/System/Video/inputs/channels',
    '/ISAPI/Smart/capabilities',
    '/ISAPI/Intelligent/capabilities',
    '/ISAPI/System/Video/inputs/channels/{ch}/counting/capabilities',
    '/ISAPI/System/Video/inputs/channels/{ch}/counting',
)


def counting_path(channel, suffix=''):
    return f'/ISAPI/System/Video/inputs/channels/{channel}/counting{suffix}'


def supported_counting_model(model):
    normalized = str(model or '').strip().upper()
    return normalized.startswith(('DS-2CD6825G0', 'IDS-2CD7146G0'))


def video_channels(camera):
    """Canales de video del equipo (cámara multilente o NVR); 1 si no los informa."""
    try:
        tree = xml_tree(request(camera, '/ISAPI/System/Video/inputs/channels'))
    except CameraError:
        return ['1']
    ids = [node.findtext('id') for node in tree.iter('VideoInputChannel')]
    return [value for value in ids if value and value.isdigit()] or ['1']


def save_capabilities(camera, folder, channels):
    folder.mkdir(parents=True, exist_ok=True)
    summary = {}
    for template in CAPABILITY_PATHS:
        for channel in (channels if '{ch}' in template else [None]):
            path = template.format(ch=channel)
            name = path.strip('/').replace('/', '_') + '.xml'
            try:
                (folder / name).write_bytes(request(camera, path))
                summary[path] = 'ok'
            except CameraError as exc:
                summary[path] = str(exc)
    (folder / 'resumen.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def probe(camera):
    raw = request(camera, '/ISAPI/System/deviceInfo')
    tree = xml_tree(raw)
    stable_id = tree.findtext('serialNumber') or tree.findtext('macAddress')
    if not stable_id:
        raise CameraError('La cámara no entregó un identificador estable.')
    model = tree.findtext('model') or ''
    updated = dict(camera, external_id=stable_id, model=model,
                   firmware=tree.findtext('firmwareVersion') or '')
    # Se habilita por capacidad, no por modelo: cualquier cámara que exponga la
    # configuración ISAPI de conteo de personas usa el mismo extractor validado.
    channels = video_channels(camera)
    settings, channel = None, None
    for candidate in channels:
        try:
            tree_counting = xml_tree(request(camera, counting_path(candidate)))
        except CameraError:
            continue
        if tree_counting.tag == 'Counting':
            settings, channel = tree_counting, candidate
            break
    if settings is not None:
        regions = settings.findall('.//CountingRegion')
        if len(regions) > 1:
            raise CameraError('Este extractor requiere una única región; no se acumularon regiones.')
        # DeepinView can expose one global counting rule without CountingRegionList.
        region = regions[0].findtext('id') if regions else '1'
        if not region or not region.isdigit():
            raise CameraError('La cámara no entregó una región válida.')
        updated.update(source_kind='people_counter', direction='bidirectional', region='r'+region,
                       region_id=region, query_method='ISAPI counting/search · HTTP Digest',
                       counting_enabled=str(settings.findtext('enabled') or '').lower() == 'true',
                       counting_model_supported=supported_counting_model(model), channel_id=channel)
    else:
        updated.update(source_kind='', counting_enabled=False)
    creds = read_secret('camera/' + camera['external_id']) or read_secret('camera-default')
    store_secret('camera/' + stable_id, creds)
    updated['connection_status'] = 'Conectada'
    source = ROOT / 'sources' / hashlib.sha256(stable_id.encode()).hexdigest()
    source.mkdir(parents=True, exist_ok=True)
    (source / 'deviceInfo.xml').write_bytes(raw)
    save_capabilities(camera, source / 'capacidades', channels)
    return updated


def parse_counts(raw, day, zone):
    tree = xml_tree(raw)
    if tree.tag != 'CountingStatisticsResult' or tree.findtext('responseStatus') != 'true':
        raise CameraError('La consulta de conteos falló; no se generaron ceros.')
    elements = tree.findall('./matchList/matchElement')
    try:
        matches = int(tree.findtext('numOfMatches'))
    except (TypeError, ValueError):
        raise CameraError('La cámara no confirmó la cantidad de intervalos.') from None
    if not elements or matches != len(elements):
        raise CameraError('No hay datos completos para esa fecha; no se generaron ceros.')
    intervals = []
    for item in elements:
        values = [item.findtext(k) for k in ('enterCount', 'exitCount')]
        if any(v is None or not re.fullmatch(r'\d+', v) for v in values):
            raise CameraError('Falta Entradas o Salidas en un intervalo; no se reemplazó por cero.')
        try:
            times = [datetime.fromisoformat(item.findtext('timeSpan/' + k)) for k in ('startTime', 'endTime')]
        except (TypeError, ValueError):
            raise CameraError('La cámara entregó fechas inválidas.') from None
        # This firmware reports inclusive seconds (00:00:00 through 00:59:59).
        start, end = times
        if any(t.tzinfo is None and t.replace(tzinfo=zone, fold=0).utcoffset() != t.replace(tzinfo=zone, fold=1).utcoffset() for t in times):
            raise CameraError('Hora ambigua por cambio de horario. Se requiere confirmar el offset de la fuente.')
        start = start.replace(tzinfo=zone) if start.tzinfo is None else start.astimezone(zone)
        end = end.replace(tzinfo=zone) if end.tzinfo is None else end.astimezone(zone)
        end += timedelta(seconds=1)
        if start.date() != day or start >= end or end > datetime.combine(day + timedelta(days=1), datetime.min.time(), zone):
            raise CameraError('El intervalo no corresponde a la fecha consultada.')
        intervals.append({'start': start.isoformat(), 'end': end.isoformat(),
                          'entries': int(values[0]), 'exits': int(values[1])})
    intervals.sort(key=lambda item: item['start'])
    for previous, current in zip(intervals, intervals[1:]):
        if datetime.fromisoformat(current['start']) < datetime.fromisoformat(previous['end']):
            raise CameraError('La cámara devolvió intervalos superpuestos.')
    return intervals


def extract_day(camera, day, timezone_name, centre_id=None):
    zone = ZoneInfo(timezone_name)
    if isinstance(day, str):
        day = date.fromisoformat(day)
    if day >= datetime.now(zone).date():
        raise CameraError('Seleccione un día terminado para evitar conteos parciales.')
    if camera.get('source_kind') != 'people_counter':
        model = camera.get('model') or 'modelo desconocido'
        raise CameraError(f'La cámara ({model}) no expone conteo de personas por ISAPI. '
                          'Pruebe la conexión nuevamente o informe el modelo.')
    if not camera.get('counting_enabled'):
        raise CameraError('El conteo está deshabilitado en la cámara.')
    region = str(camera.get('region_id', ''))
    if not region.isdigit():
        raise CameraError('Primero pruebe la conexión para identificar la región de conteo.')
    key = json.dumps([centre_id, camera['external_id'], camera['source_kind'], region, camera['direction'], day.isoformat(), timezone_name], separators=(',', ':'))
    batch_id = str(uuid.uuid5(uuid.NAMESPACE_URL, key))
    folder = ROOT / 'batches' / batch_id
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / 'extract.lock'
    # Windows releases this OS lock automatically after a crash/restart.
    from relleno.locks import exclusive_byte
    with lock.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        try:
            with exclusive_byte(handle):
                report = folder / 'people.json'
                if report.exists():
                    return json.loads(report.read_text(encoding='utf-8'))
                root = ET.Element('CountingStatisticsDescription')
                ET.SubElement(root, 'statisticType').text = 'all'
                ET.SubElement(root, 'reportType').text = 'daily'
                span = ET.SubElement(ET.SubElement(root, 'timeSpanList'), 'timeSpan')
                ET.SubElement(span, 'startTime').text = day.isoformat() + 'T00:00:00'
                ET.SubElement(span, 'endTime').text = day.isoformat() + 'T23:59:59'
                ET.SubElement(root, 'child').text = 'false'
                ET.SubElement(root, 'regionID').text = region
                raw = request(camera, counting_path(camera.get('channel_id') or '1', '/search'), ET.tostring(root, encoding='utf-8'))
                (folder / ('source-' + uuid.uuid4().hex + '.xml')).write_bytes(raw)
                intervals = parse_counts(raw, day, zone)
                data = dict(schema_version=1, data_type='personas', source_kind=camera['source_kind'],
                            batch_id=batch_id, timezone=timezone_name,
                            camera={k: camera[k] for k in ('external_id', 'name', 'ip', 'region', 'direction')},
                            intervals=intervals)
                temporary = folder / 'people.tmp'
                temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
                temporary.replace(report)
                return data
        except BlockingIOError:
            raise CameraError('Esta ventana ya se está consultando.') from None


def parse_inventory(text):
    cameras = []
    for line in text.splitlines():
        if not line.strip():
            continue
        columns = [part.strip().rstrip('\\') for part in re.split(r'\t+|;', line.strip())]
        if len(columns) != 4:
            raise CameraError('Pegue cuatro columnas: Nombre, Nivel, Grupo e IP, separadas por tabulaciones o punto y coma.')
        name, location, group, host = columns
        host_url(host)
        if not all(columns):
            raise CameraError('Todas las columnas son obligatorias.')
        if any(item['ip'] == host for item in cameras):
            raise CameraError('La lista repite una dirección de cámara.')
        cameras.append(dict(external_id='pending-' + hashlib.sha256(host.encode()).hexdigest()[:16],
                            name=name, location=location, group=group, ip=host,
                            region='pending', direction='pending', source_kind='pending',
                            model='', firmware='', query_method='Pendiente de probar conexión'))
    if not cameras:
        raise CameraError('Pegue al menos una cámara.')
    return cameras
