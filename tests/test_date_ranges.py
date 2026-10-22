import unittest
from datetime import datetime
from unittest.mock import patch

from relleno.date_ranges import completed_days


class CompletedDaysTests(unittest.TestCase):
    @patch('relleno.date_ranges.datetime')
    def test_inclusive_range_contains_only_completed_days(self, clock):
        clock.now.return_value = datetime(2026, 10, 22, 12)
        self.assertEqual(
            [str(day) for day in completed_days('2026-10-19', '2026-10-21', 'America/Santiago')],
            ['2026-10-19', '2026-10-20', '2026-10-21'],
        )
        with self.assertRaisesRegex(ValueError, 'terminados'):
            completed_days('2026-10-21', '2026-10-22', 'America/Santiago')

    def test_rejects_reversed_invalid_and_excessive_ranges(self):
        with self.assertRaisesRegex(ValueError, 'Hasta'):
            completed_days('2026-10-20', '2026-10-19', 'America/Santiago')
        with self.assertRaisesRegex(ValueError, 'formato'):
            completed_days('20-10-2026', '2026-10-20', 'America/Santiago')
        with self.assertRaisesRegex(ValueError, '31'):
            completed_days('2026-01-01', '2026-02-01', 'America/Santiago')


if __name__ == '__main__':
    unittest.main()
