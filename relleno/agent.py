"""Portal heartbeat and remote generation commands for the Windows worker."""
from relleno.cameras import extract_day, probe, CameraConnectionError, estimated_zero_day
from relleno.people import send_batch
from relleno.portal import CLIENT_VERSION, agent_post, upload_diagnostic
from relleno.storage import read_secret, save


def capabilities(config):
    result = []
    if any(
        (camera.get('counting_enabled') and camera.get('source_kind') in {'people_counter', 'rf_counter'})
        or camera.get('source_kind') == 'pending'
        for camera in config.get('cameras', [])
    ):
        result.append('personas')
    hikcentral = config.get('hikcentral') or {}
    credentials = read_secret('hikcentral')
    if hikcentral.get('url') and credentials and credentials.get('method') == 'username':
        result.append('vehiculos')
        result.append('diagnostico')
    return result


def heartbeat(config):
    binding = config['binding']
    return agent_post(binding, 'heartbeat_url', {
        'client_version': CLIENT_VERSION,
        'capabilities': capabilities(config),
    })


def poll_command(config):
    return agent_post(config['binding'], 'commands_url', {}).get('command')


def complete_command(config, command, state, message, receipt_ids=None, diagnostic_id=None):
    return agent_post(config['binding'], 'command_result_url', {
        'command_id': command['id'],
        'state': state,
        'message': message,
        'receipt_ids': receipt_ids or [],
        'diagnostic_id': diagnostic_id or '',
    })


def collect_people(camera, day, timezone_name, centre_id):
    current = camera
    try:
        if current.get('source_kind') in {'', 'pending', None} or not current.get('counting_enabled'):
            current = probe(current)
        batch = extract_day(current, day, timezone_name, centre_id)
    except CameraConnectionError:
        batch = estimated_zero_day(current, day, timezone_name, centre_id)
    return current, batch


def generate_people(config, day):
    fingerprints_before = {
        (camera.get('external_id'), camera.get('ip')): camera.get('https_fingerprint')
        for camera in config.get('cameras', [])
    }
    refreshed, receipts, errors = [], [], []
    changed = False
    for camera in config.get('cameras', []):
        current = camera
        if camera.get('source_kind') == 'anpr':
            refreshed.append(current)
            continue
        try:
            changed = changed or camera.get('source_kind') in {'', 'pending', None} or not camera.get('counting_enabled')
            current, batch = collect_people(camera, day, config.get('timezone', 'America/Santiago'),
                                            config['binding']['centre_id'])
            receipts.append(send_batch(config['binding'], batch))
        except Exception as exc:
            errors.append(f"{camera.get('name', 'Camera')}: {exc}")
        refreshed.append(current)
    config['cameras'] = refreshed
    pin_changed = any(
        fingerprints_before.get((camera.get('external_id'), camera.get('ip'))) != camera.get('https_fingerprint')
        for camera in refreshed
    )
    if changed or pin_changed:
        save(config)
    if errors:
        raise ValueError('No se completaron todas las camaras. ' + ' | '.join(errors[:5]))
    if not receipts:
        raise ValueError('No hay camaras de Personas configuradas.')
    return receipts


def generate_anpr(config, day, outbox):
    from relleno.anpr_schedule import export_and_enqueue

    batch_id = export_and_enqueue(config, day, outbox)
    outbox.drain(config)
    row = next((item for item in outbox.list() if item['batch_id'] == batch_id), None)
    if not row or row['state'] != 'delivered' or not row.get('receipt_id'):
        detail = row.get('message') if row else 'La exportación no ingresó a la cola.'
        raise ValueError(detail or 'El portal no confirmó la recepción ANPR.')
    return [row['receipt_id']]


def execute_command(config, command, outbox):
    if command['data_type'] == 'personas':
        receipts = generate_people(config, command['day'])
    elif command['data_type'] == 'vehiculos':
        receipts = generate_anpr(config, command['day'], outbox)
    elif command['data_type'] == 'diagnostico':
        from relleno.diagnostics import run_hikcentral
        archive, successful, message = run_hikcentral(config, command['day'])
        try:
            diagnostic_id = upload_diagnostic(config['binding'], archive, command['id'])
        finally:
            archive.unlink(missing_ok=True)
        return {'diagnostic_id': diagnostic_id, 'successful': successful, 'message': message}
    else:
        raise ValueError('El portal envió un tipo de generación desconocido.')
    return receipts
