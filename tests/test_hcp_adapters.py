from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from openpyxl import load_workbook

from relleno.hcp_adapters import AdapterError, BumblebeeVehicleLogsAdapter, capture_kind


def payload(page, rows, total=None):
    data = {'PageIndex': page, 'PageSize': 2, 'VehicleLog': rows}
    if total is not None:
        data['TotalNum'] = total
    return {'ResponseStatus': {'Data': {'VehicleLogsList': data}, 'ErrorCode': 0}}


def response(url, data, body=None):
    value = Mock()
    value.url = url
    value.status = 200
    value.json.return_value = data
    value.request.method = 'POST'
    value.request.headers = {
        'content-type': 'application/json',
        'cookie': 'SID=must-not-be-copied',
        'authorization': 'must-not-be-copied',
    }
    value.request.post_data_json = body or {'SearchRequest': {'PageIndex': 1, 'PageSize': 2}}
    return value


class BumblebeeAdapterTests(unittest.TestCase):
    def test_detects_only_same_origin_exact_family(self):
        item = response(
            'https://127.0.0.1/ISAPI/Bumblebee/VehicleBiz/V0/LPR/VehicleLogs?MT=GET',
            {},
        )
        adapter, kind = capture_kind(item, 'https://127.0.0.1')
        self.assertIs(adapter, BumblebeeVehicleLogsAdapter)
        self.assertEqual(kind, 'list')
        self.assertEqual(capture_kind(item, 'https://other.local'), (None, None))

    def test_fetches_every_page_and_writes_anpr_excel_without_copying_session_headers(self):
        base = 'https://127.0.0.1/ISAPI/Bumblebee/VehicleBiz/V0/LPR/'
        count = response(base + 'VehicleLogsCount?MT=GET', payload(1, [], 3))
        first = response(base + 'VehicleLogs?MT=GET', payload(1, [
            {'GUID':'a', 'PassTime':'2026-10-21T10:00:00-03:00', 'PlateLicense':'AA11', 'ResourceName':'CAM 1'},
            {'GUID':'b', 'PassTime':'2026-10-21T11:00:00-03:00', 'PlateLicense':'BB22', 'ResourceName':'CAM 2'},
        ], 2))
        second = Mock()
        second.status = 200
        second.json.return_value = payload(2, [
            {'GUID':'c', 'PassTime':'2026-10-21T12:00:00-03:00', 'PlateLicense':'CC33', 'ResourceName':'CAM 3'},
        ], 1)
        context = Mock()
        context.request.fetch.return_value = second

        with tempfile.TemporaryDirectory() as directory:
            source, evidence = BumblebeeVehicleLogsAdapter.extract(
                context, {'count':count, 'list':first}, date(2026, 10, 21), Path(directory)
            )
            self.assertEqual(evidence['count'], 3)
            workbook = load_workbook(source, read_only=True)
            try:
                rows = list(workbook.active.values)
            finally:
                workbook.close()
            self.assertEqual(len(rows), 4)
            self.assertEqual(rows[1][1:3], ('AA11', 'CAM 1'))

        call = context.request.fetch.call_args
        sent_headers = {key.casefold() for key in call.kwargs['headers']}
        self.assertNotIn('cookie', sent_headers)
        self.assertNotIn('authorization', sent_headers)
        self.assertEqual(json.loads(call.kwargs['data'])['SearchRequest']['PageIndex'], 2)

    def test_rejects_repeated_or_incomplete_pages(self):
        base = 'https://127.0.0.1/ISAPI/Bumblebee/VehicleBiz/V0/LPR/'
        count = response(base + 'VehicleLogsCount?MT=GET', payload(1, [], 3))
        first_row = {'GUID':'same', 'PassTime':'2026-10-21T10:00:00-03:00'}
        first = response(base + 'VehicleLogs?MT=GET', payload(1, [first_row], 1),
                         {'PageIndex':1, 'PageSize':1})
        repeated = Mock(status=200)
        repeated.json.return_value = payload(2, [first_row], 1)
        context = Mock()
        context.request.fetch.return_value = repeated
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AdapterError, 'repitió'):
                BumblebeeVehicleLogsAdapter.extract(
                    context, {'count':count, 'list':first}, date(2026, 10, 21), Path(directory)
                )

    def test_rejects_rows_from_another_day(self):
        base = 'https://127.0.0.1/ISAPI/Bumblebee/VehicleBiz/V0/LPR/'
        count = response(base + 'VehicleLogsCount?MT=GET', payload(1, [], 1))
        first = response(base + 'VehicleLogs?MT=GET', payload(1, [
            {'GUID':'a', 'PassTime':'2026-10-20T23:59:59-03:00'},
        ], 1))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(AdapterError, 'fuera del día'):
                BumblebeeVehicleLogsAdapter.extract(
                    Mock(), {'count':count, 'list':first}, date(2026, 10, 21), Path(directory)
                )


if __name__ == '__main__':
    unittest.main()
