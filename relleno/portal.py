from urllib.parse import urlsplit, urljoin
import requests

BASE = 'https://siem.domoticatechnology.cl/relleno'
CLIENT_VERSION = '0.4.21'


class PortalError(ValueError):
    """Only messages safe to display; never include raw server responses."""


def endpoint(base, value):
    original = urlsplit(base)
    # Django is mounted below /relleno; a returned /api/... is app-relative.
    if value.startswith('/api/'):
        value = value.lstrip('/')
    url = urljoin(base.rstrip('/') + '/', value)
    parsed = urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError('URL del portal inválida.')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname == 'localhost'):
        raise ValueError('El portal requiere HTTPS.')
    if (parsed.scheme, parsed.netloc) != (original.scheme, original.netloc):
        raise ValueError('El destino debe pertenecer al mismo portal.')
    return url


def link(code, name):
    try:
        response = requests.post(BASE + '/api/comprobaciones/agentes/vincular/',
                                 json={'code': code.strip().upper(), 'agent_name': name.strip()},
                                 timeout=(10, 40), allow_redirects=False)
    except requests.exceptions.SSLError:
        raise PortalError('No se pudo verificar el certificado HTTPS del portal.') from None
    except requests.RequestException:
        raise PortalError('No se pudo conectar al portal. Revise Internet y vuelva a intentar.') from None
    if response.status_code in (400, 401, 404, 410):
        raise PortalError('El código no existe, expiró o ya fue utilizado. Genere uno nuevo en Comprobaciones.')
    if response.status_code == 429:
        raise PortalError('Demasiados intentos. Espere antes de generar y usar otro código.')
    if response.status_code not in (200, 201):
        raise PortalError(f'El portal rechazó la vinculación (HTTP {response.status_code}).')
    try:
        data = response.json()
    except ValueError:
        raise PortalError('El portal no devolvió una respuesta JSON válida.') from None
    if not isinstance(data, dict) or data.get('ok') is not True or not all(data.get(k) for k in ('agent_id', 'agent_token', 'centre_id', 'centre_name', 'upload_url')):
        raise PortalError('El portal devolvió una vinculación incompleta.')
    # Preserve a successful one-use response securely before further processing.
    from relleno.storage import store_secret
    store_secret('portal-recovery', {k: data[k] for k in ('agent_id', 'agent_token', 'centre_id', 'centre_name', 'upload_url', 'people_count_url', 'heartbeat_url', 'commands_url', 'command_result_url') if k in data})
    data['upload_url'] = endpoint(BASE, data['upload_url'])
    if data.get('people_count_url'):
        data['people_count_url'] = endpoint(BASE, data['people_count_url'])
        if data['people_count_url'] == data['upload_url']:
            raise ValueError('El canal Personas no puede usar el destino ANPR.')
    for key in ('heartbeat_url', 'commands_url', 'command_result_url'):
        if data.get(key):
            data[key] = endpoint(BASE, data[key])
    return data


def persist_binding(data):
    from relleno.storage import load, save, store_secret
    store_secret('portal/' + str(data['agent_id']), {'token': data['agent_token']})
    binding = {k: data[k] for k in ('agent_id', 'centre_id', 'centre_name', 'upload_url', 'people_count_url', 'heartbeat_url', 'commands_url', 'command_result_url') if k in data}
    binding['upload_url'] = endpoint(BASE, binding['upload_url'])
    if binding.get('people_count_url'):
        binding['people_count_url'] = endpoint(BASE, binding['people_count_url'])
        if binding['people_count_url'] == binding['upload_url']:
            raise PortalError('El canal Personas no puede usar el destino ANPR.')
    for key in ('heartbeat_url', 'commands_url', 'command_result_url'):
        if binding.get(key):
            binding[key] = endpoint(BASE, binding[key])
    config = load()
    config['binding'] = binding
    save(config)
    return config


def binding_endpoint(binding, key):
    defaults = {
        'people_count_url': '/api/comprobaciones/agentes/personas/',
        'heartbeat_url': '/api/comprobaciones/agentes/pulso/',
        'commands_url': '/api/comprobaciones/agentes/ordenes/',
        'command_result_url': '/api/comprobaciones/agentes/ordenes/resultado/',
    }
    value = binding.get(key) or defaults.get(key)
    if not value:
        raise PortalError('La vinculación no incluye el canal solicitado.')
    return endpoint(BASE, value)


def agent_token(binding):
    from relleno.storage import read_secret
    secret = read_secret('portal/' + str(binding['agent_id']))
    if not secret or not secret.get('token'):
        raise PortalError('No se encontró el token del equipo en Windows.')
    return secret['token']


def agent_post(binding, key, payload):
    url = binding_endpoint(binding, key)
    try:
        response = requests.post(
            url,
            headers={'Authorization': 'Bearer ' + agent_token(binding)},
            json=payload,
            timeout=(10, 120),
            allow_redirects=False,
        )
    except requests.exceptions.SSLError:
        raise PortalError('No se pudo verificar el certificado HTTPS del portal.') from None
    except requests.RequestException:
        raise PortalError('No se pudo conectar al portal.') from None
    try:
        data = response.json()
    except ValueError:
        data = None
    if not 200 <= response.status_code < 300 or not isinstance(data, dict) or data.get('ok') is not True:
        detail = data.get('error') if isinstance(data, dict) else None
        detail = ' '.join(str(detail or '').split())[:300]
        suffix = ': ' + detail if detail else '.'
        raise PortalError(f'El portal rechazó la solicitud (HTTP {response.status_code}){suffix}')
    return data
