from urllib.parse import urlsplit
import requests
from requests.adapters import HTTPAdapter


def normalize_url(value):
    value = value.strip().rstrip('/')
    if '://' not in value:
        value = 'https://' + value
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Ingrese una dirección de HikCentral sin credenciales ni parámetros.')
    parsed.port  # Validate the optional port before opening a connection.
    return value


class PinnedAdapter(HTTPAdapter):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs['assert_fingerprint'] = self.fingerprint
        return super().init_poolmanager(*args, **kwargs)


def check(settings):
    url = normalize_url(settings['url'])
    parsed = urlsplit(url)
    with requests.Session() as session:
        verify = True
        # A pin provisioned on this machine is valid only for the local server.
        if parsed.scheme == 'https' and parsed.hostname in ('127.0.0.1', 'localhost', '::1') and settings.get('certificate_sha256'):
            session.mount(url, PinnedAdapter(settings['certificate_sha256']))
            verify = False  # Certificate is verified by its SHA-256 fingerprint.
        session.trust_env = False
        try:
            response = session.get(url, timeout=(5, 15), allow_redirects=False, verify=verify)
        except requests.exceptions.SSLError:
            raise ValueError('No se pudo verificar el certificado de HikCentral. Revise su certificado o la huella local configurada.') from None
        except requests.RequestException:
            raise ValueError('No se pudo conectar a HikCentral. Revise la dirección y el puerto.') from None
        if response.status_code != 200 or 'Web Client' not in response.text:
            raise ValueError(f'El destino no devolvió el portal web de HikCentral (HTTP {response.status_code}).')
    return 'Portal web accesible. Autenticación y extracción ANPR pendientes de validar.'
