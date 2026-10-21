from urllib.parse import urljoin, urlsplit
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
            current = url
            for _ in range(5):
                response = session.get(current, timeout=(5, 15), allow_redirects=False, verify=verify)
                if response.status_code not in {301, 302, 303, 307, 308}:
                    break
                location = str(response.headers.get('Location') or '').strip()
                if not location:
                    raise ValueError('HikCentral devolvió una redirección sin destino.')
                target = urljoin(current + '/', location)
                source, destination = urlsplit(url), urlsplit(target)
                source_port = source.port or (443 if source.scheme == 'https' else 80)
                target_port = destination.port or (443 if destination.scheme == 'https' else 80)
                if (destination.scheme, destination.hostname, target_port) != (
                    source.scheme, source.hostname, source_port
                ):
                    raise ValueError('HikCentral redirigió hacia otro servidor; revise la URL configurada.')
                current = target
            else:
                raise ValueError('HikCentral excedió el máximo de redirecciones.')
        except requests.exceptions.SSLError:
            raise ValueError('No se pudo verificar el certificado de HikCentral. Revise su certificado o la huella local configurada.') from None
        except requests.exceptions.ConnectTimeout:
            raise ValueError('HikCentral no respondió al intentar conectar. Revise IP, puerto y firewall.') from None
        except requests.exceptions.ReadTimeout:
            raise ValueError('HikCentral aceptó la conexión, pero no respondió dentro de 15 segundos.') from None
        except requests.exceptions.ConnectionError:
            raise ValueError('No se pudo conectar a HikCentral. Revise la dirección y el puerto.') from None
        except requests.RequestException:
            raise ValueError('La conexión HTTP con HikCentral no pudo completarse.') from None
        page = str(response.text or '').lower()
        if response.status_code != 200 or not any(marker in page for marker in ('hikcentral', 'web client')):
            raise ValueError(f'El destino no devolvió el portal web de HikCentral (HTTP {response.status_code}).')
    return 'Portal web accesible. Autenticación y extracción ANPR pendientes de validar.'
