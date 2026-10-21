from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from relleno.people_schedule import pending_days


class PeopleScheduleTests(unittest.TestCase):
    def test_waits_until_one_and_preserves_pending_days(self):
        config = {
            'timezone': 'America/Santiago',
            'people': {'export_since': '2026-10-18'},
        }
        before_one = datetime(2026, 10, 21, 0, 30, tzinfo=ZoneInfo('America/Santiago'))
        after_one = datetime(2026, 10, 21, 1, 1, tzinfo=ZoneInfo('America/Santiago'))
        self.assertEqual([str(day) for day in pending_days(config, before_one)], ['2026-10-18', '2026-10-19'])
        self.assertEqual([str(day) for day in pending_days(config, after_one)], ['2026-10-18', '2026-10-19', '2026-10-20'])


if __name__ == '__main__':
    unittest.main()
