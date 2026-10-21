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


def probe(camera):
    raw = request(camera, '/ISAPI/System/deviceInfo')
    tree = xml_tree(raw)
    stable_id = tree.findtext('serialNumber') or tree.findtext('macAddress')
    if not stable_id:
        raise CameraError('La cámara no entregó un identificador estable.')
    model = tree.findtext('model') or ''
    updated = dict(camera, external_id=stable_id, model=model,
                   firmware=tree.findtext('firmwareVersion') or '')
    if model.startswith('DS-2CD6825'):
        settings = xml_tree(request(camera, '/ISAPI/System/Video/inputs/channels/1/counting'))
        regions = settings.findall('./CountingRegionList/CountingRegion')
        if len(regions) != 1:
            raise CameraError('Este extractor requiere una única región; no se acumularon regiones.')
        region = regions[0].findtext('id')
        if not region or not region.isdigit():
            raise CameraError('La cámara no entregó una región válida.')
        updated.update(source_kind='people_counter', direction='bidirectional', region='r'+region,
                       region_id=region, query_method='ISAPI counting/search · HTTP Digest',
                       counting_enabled=settings.findtext('enabled') == 'true')
    creds = read_secret('camera/' + camera['external_id']) or read_secret('camera-default')
    store_secret('camera/' + stable_id, creds)
    updated['connection_status'] = 'Conectada'
    source = ROOT / 'sources' / hashlib.sha256(stable_id.encode()).hexdigest()
    source.mkdir(parents=True, exist_ok=True)
    (source / 'deviceInfo.xml').write_bytes(raw)
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
    if camera.get('source_kind') != 'people_counter' or not camera.get('model', '').startswith('DS-2CD6825'):
        raise CameraError('El modelo de esta cámara aún no tiene extractor validado.')
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
    import msvcrt
    with lock.open('a+b') as handle:
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise CameraError('Esta ventana ya se está consultando.') from None
        try:
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
            raw = request(camera, '/ISAPI/System/Video/inputs/channels/1/counting/search', ET.tostring(root, encoding='utf-8'))
            (folder / ('source-' + uuid.uuid4().hex + '.xml')).write_bytes(raw)
            intervals = parse_counts(raw, day, zone)
            data = dict(schema_version=1, data_type='personas', source_kind=camera['source_kind'],
                        batch_id=batch_id, timezone=timezone_name,
                        camera={k: camera[k] for k in ('external_id', 'name', 'ip', 'region', 'direction')},
                        intervals=intervals)
            # No portal destination is used here; keep source and batch locally.
            temporary = folder / 'people.tmp'
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
            temporary.replace(report)
            return data
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


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
