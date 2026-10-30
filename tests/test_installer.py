import unittest
from pathlib import Path


class InstallerTests(unittest.TestCase):
    def test_silent_update_restarts_agent_and_visible_application(self):
        script = Path(__file__).resolve().parents[1].joinpath("installer.iss").read_text(encoding="utf-8")

        self.assertIn('Parameters: "--resume-agent"; Flags: runhidden nowait', script)
        self.assertIn('Filename: "{app}\\RellenoCliente.exe"; Flags: nowait; Check: WizardSilent', script)
        self.assertNotIn("waituntilterminated", script)
        self.assertIn("'/F /IM RellenoCliente.exe'", script)
        self.assertNotIn("'/F /T /IM RellenoCliente.exe'", script)


if __name__ == "__main__":
    unittest.main()
