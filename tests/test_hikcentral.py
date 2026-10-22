import unittest
from unittest.mock import Mock, patch
from relleno.hikcentral import normalize_url, check, is_local_url, read_certificate_fingerprint


class HikCentralTests(unittest.TestCase):
    def test_bare_address_and_no_credentials(self):
        self.assertEqual(normalize_url('localhost:443'), 'https://localhost:443')
        for url in ('https://user:secret@localhost', 'https://localhost/?token=test', 'https://localhost:invalid'):
            with self.assertRaises(ValueError):
                normalize_url(url)

    @patch('relleno.hikcentral.requests.Session')
    def test_web_probe_sends_no_credentials_and_preserves_tls(self, session):
        request = session.return_value.__enter__.return_value.get
        request.return_value.status_code = 200
        request.return_value.text = '<title>Web Client</title>'
        self.assertIn('pendientes', check({'url':'https://hikcentral.invalid'}))
        self.assertTrue(request.call_args.kwargs['verify'])
        self.assertNotIn('auth', request.call_args.kwargs)

    @patch('relleno.hikcentral.requests.Session')
    def test_web_probe_follows_only_same_hikcentral_origin(self, session):
        request = session.return_value.__enter__.return_value.get
        redirect = Mock(status_code=302, headers={'Location': '/portal/'}, text='')
        portal = Mock(status_code=200, headers={}, text='<title>HikCentral Web Client</title>')
        request.side_effect = [redirect, portal]

        self.assertIn('accesible', check({'url': 'https://hikcentral.invalid:443'}))
        self.assertEqual(request.call_args_list[1].args[0], 'https://hikcentral.invalid:443/portal/')

    @patch('relleno.hikcentral.requests.Session')
    def test_web_probe_rejects_cross_server_redirect(self, session):
        request = session.return_value.__enter__.return_value.get
        request.return_value = Mock(
            status_code=302, headers={'Location': 'https://other.invalid/login'}, text=''
        )
        with self.assertRaisesRegex(ValueError, 'otro servidor'):
            check({'url': 'https://hikcentral.invalid'})

    @patch('relleno.hikcentral.ssl.create_default_context')
    @patch('relleno.hikcentral.socket.create_connection')
    def test_certificate_fingerprint_is_sha256_of_server_certificate(self, connection, context):
        raw = connection.return_value.__enter__.return_value
        tls = context.return_value.wrap_socket.return_value.__enter__.return_value
        tls.getpeercert.return_value = b'certificate'

        self.assertEqual(
            read_certificate_fingerprint('https://hikcentral.invalid:8443'),
            '03d66dd08835c1ca3f128cceacd1f31ac94163096b20f445ae84285bc0832d72',
        )
        connection.assert_called_once_with(('hikcentral.invalid', 8443), timeout=5)
        context.return_value.wrap_socket.assert_called_once_with(raw, server_hostname='hikcentral.invalid')

    @patch('relleno.hikcentral.requests.Session')
    def test_saved_certificate_pin_is_used_for_non_local_server(self, session):
        request = session.return_value.__enter__.return_value.get
        request.return_value = Mock(status_code=200, headers={}, text='HikCentral')

        check({'url': 'https://192.168.1.20', 'certificate_sha256': 'ab' * 32})

        session.return_value.__enter__.return_value.mount.assert_called_once()
        self.assertFalse(request.call_args.kwargs['verify'])

    @patch('relleno.hikcentral.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))])
    def test_local_hikcentral_url_is_detected(self, resolve):
        self.assertTrue(is_local_url('https://localhost'))
        resolve.return_value = [(2, 1, 6, '', ('8.8.8.8', 443))]
        self.assertFalse(is_local_url('https://example.com'))
