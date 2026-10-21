import unittest
from unittest.mock import patch
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
