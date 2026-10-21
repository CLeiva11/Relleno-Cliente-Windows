from urllib.parse import urlsplit, urljoin
import requests

BASE = 'https://siem.domoticatechnology.cl/relleno'


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
    store_secret('portal-recovery', {k: data[k] for k in ('agent_id', 'agent_token', 'centre_id', 'centre_name', 'upload_url', 'people_count_url') if k in data})
    data['upload_url'] = endpoint(BASE, data['upload_url'])
    if data.get('people_count_url'):
        data['people_count_url'] = endpoint(BASE, data['people_count_url'])
        if data['people_count_url'] == data['upload_url']:
            raise ValueError('El canal Personas no puede usar el destino ANPR.')
    return data


def persist_binding(data):
    from relleno.storage import load, save, store_secret
    store_secret('portal/' + str(data['agent_id']), {'token': data['agent_token']})
    binding = {k: data[k] for k in ('agent_id', 'centre_id', 'centre_name', 'upload_url', 'people_count_url') if k in data}
    binding['upload_url'] = endpoint(BASE, binding['upload_url'])
    if binding.get('people_count_url'):
        binding['people_count_url'] = endpoint(BASE, binding['people_count_url'])
        if binding['people_count_url'] == binding['upload_url']:
            raise PortalError('El canal Personas no puede usar el destino ANPR.')
    config = load()
    config['binding'] = binding
    save(config)
    return config
