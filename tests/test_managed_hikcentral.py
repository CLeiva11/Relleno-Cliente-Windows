import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relleno.hcp_export import ExportError, download
from relleno.managed_hikcentral import apply, credentials


class ManagedHikCentralTests(unittest.TestCase):
    def test_managed_endpoint_replaces_local_configuration(self):
        config = {"hikcentral": {"url": "https://otro-servidor", "certificate_sha256": "abc"}}

        self.assertTrue(apply(config))
        self.assertEqual(config["hikcentral"]["url"], "https://127.0.0.1")
        self.assertEqual(config["hikcentral"]["method"], "username")
        self.assertEqual(config["hikcentral"]["certificate_sha256"], "abc")

    def test_credentials_are_supplied_outside_source_control(self):
        with patch.dict(os.environ, {"RELLENO_HIKCENTRAL_PASSWORDS": "first|second"}):
            values = credentials()

        self.assertEqual(values["account"], "admin")
        self.assertEqual(values["secrets"], ("first", "second"))

    @patch("relleno.hcp_export._download")
    def test_second_managed_password_is_tried_only_after_auth_rejection(self, implementation):
        implementation.side_effect = [
            ExportError("HikCentral no aceptó el inicio de sesión. No se repitió la contraseña."),
            (Path("ok.xlsx"), {"native": True}),
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = download(
                {"hikcentral": {"url": "https://127.0.0.1"}},
                "2026-10-29",
                {"account": "admin", "secrets": ("first", "second")},
                Path(directory),
            )

        self.assertEqual(result[0], Path("ok.xlsx"))
        self.assertEqual(
            [call.args[2]["secret"] for call in implementation.call_args_list],
            ["first", "second"],
        )


if __name__ == "__main__":
    unittest.main()
