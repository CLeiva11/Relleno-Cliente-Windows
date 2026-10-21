"""Portal heartbeat and remote generation commands for the Windows worker."""
from relleno.cameras import extract_day
from relleno.people import send_batch
from relleno.portal import CLIENT_VERSION, agent_post
from relleno.storage import read_secret


def capabilities(config):
    result = []
    if any(
        camera.get('counting_enabled') and camera.get('source_kind') == 'people_counter'
        for camera in config.get('cameras', [])
    ):
        result.append('personas')
    hikcentral = config.get('hikcentral') or {}
    credentials = read_secret('hikcentral')
    if hikcentral.get('url') and credentials and credentials.get('method') == 'username':
        result.append('vehiculos')
    return result


def heartbeat(config):
    binding = config['binding']
    return agent_post(binding, 'heartbeat_url', {
        'client_version': CLIENT_VERSION,
        'capabilities': capabilities(config),
    })


def poll_command(config):
    return agent_post(config['binding'], 'commands_url', {}).get('command')


def complete_command(config, command, state, message, receipt_ids=None):
    return agent_post(config['binding'], 'command_result_url', {
        'command_id': command['id'],
        'state': state,
        'message': message,
        'receipt_ids': receipt_ids or [],
    })


def generate_people(config, day):
    cameras = [
        camera for camera in config.get('cameras', [])
        if camera.get('counting_enabled') and camera.get('source_kind') == 'people_counter'
    ]
    if not cameras:
        raise ValueError('No hay cámaras de Personas configuradas y habilitadas.')
    receipts = []
    errors = []
    for camera in cameras:
        try:
            batch = extract_day(
                camera, day, config.get('timezone', 'America/Santiago'),
                config['binding']['centre_id'],
            )
            receipts.append(send_batch(config['binding'], batch))
        except Exception as exc:
            errors.append(f"{camera.get('name', 'Cámara')}: {exc}")
    if errors:
        raise ValueError('No se completaron todas las cámaras. ' + ' | '.join(errors[:5]))
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
    else:
        raise ValueError('El portal envió un tipo de generación desconocido.')
    return receipts
