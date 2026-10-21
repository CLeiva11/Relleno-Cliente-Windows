import unittest
from unittest.mock import Mock, patch
from relleno.hikcentral import normalize_url, check


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
