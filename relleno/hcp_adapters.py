"""Versioned HikCentral network adapters discovered from authenticated traffic."""
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


class AdapterError(ValueError):
    pass


class BumblebeeVehicleLogsAdapter:
    """HikCentral Web Client using Bumblebee VehicleBiz V0 endpoints."""

    name = 'bumblebee-vehiclebiz-v0'
    count_path = re.compile(r'/ISAPI/Bumblebee/VehicleBiz/V0/LPR/VehicleLogsCount(?:\?|$)', re.I)
    list_path = re.compile(r'/ISAPI/Bumblebee/VehicleBiz/V0/LPR/VehicleLogs(?:\?|$)', re.I)
    safe_headers = {'accept', 'content-type', 'x-requested-with', 'x-csrf-token', 'x-xsrf-token'}

    @classmethod
    def classify(cls, response, origin):
        parsed = urlsplit(response.url)
        if f'{parsed.scheme}://{parsed.netloc}'.lower() != origin.lower():
            return None
        if response.request.method != 'POST':
            return None
        target = parsed.path + (('?' + parsed.query) if parsed.query else '')
        if cls.count_path.search(target):
            return 'count'
        if cls.list_path.search(target):
            return 'list'
        return None

    @staticmethod
    def _vehicle_list(data):
        try:
            status = data['ResponseStatus']
            if int(status.get('ErrorCode', 0)) != 0:
                raise AdapterError('HikCentral rechazó la consulta ANPR.')
            value = status['Data']['VehicleLogsList']
            return value, list(value.get('VehicleLog') or [])
        except (KeyError, TypeError, ValueError):
            raise AdapterError('La respuesta VehicleLogs de HikCentral cambió de formato.') from None

    @staticmethod
    def _count(data):
        value, _rows = BumblebeeVehicleLogsAdapter._vehicle_list(data)
        try:
            total = int(value['TotalNum'])
        except (KeyError, TypeError, ValueError):
            raise AdapterError('HikCentral no informó el total ANPR.') from None
        if total < 0 or total > 2_000_000:
            raise AdapterError('El total ANPR informado por HikCentral no es válido.')
        return total

    @staticmethod
    def _set_paging(value, page_index, page_size):
        changed_index = False
        changed_size = False
        if isinstance(value, dict):
            for key in list(value):
                folded = re.sub(r'[^a-z]', '', str(key).casefold())
                if folded == 'pageindex':
                    value[key] = page_index
                    changed_index = True
                elif folded == 'pagesize':
                    value[key] = page_size
                    changed_size = True
                else:
                    nested_index, nested_size = BumblebeeVehicleLogsAdapter._set_paging(
                        value[key], page_index, page_size
                    )
                    changed_index = changed_index or nested_index
                    changed_size = changed_size or nested_size
        elif isinstance(value, list):
            for item in value:
                nested_index, nested_size = BumblebeeVehicleLogsAdapter._set_paging(
                    item, page_index, page_size
                )
                changed_index = changed_index or nested_index
                changed_size = changed_size or nested_size
        return changed_index, changed_size

    @classmethod
    def extract(cls, context, responses, day, folder):
        count_response = responses.get('count')
        list_response = responses.get('list')
        if not count_response or not list_response:
            raise AdapterError('HikCentral no expuso ambas consultas Bumblebee.')
        if count_response.status != 200 or list_response.status != 200:
            raise AdapterError('HikCentral rechazó una página ANPR.')

        total = cls._count(count_response.json())
        first_meta, first_rows = cls._vehicle_list(list_response.json())
        try:
            page_size = int(first_meta.get('PageSize') or len(first_rows) or 100)
        except (TypeError, ValueError):
            page_size = 100
        if page_size < 1 or page_size > 1000:
            raise AdapterError('HikCentral informó una paginación ANPR inválida.')

        try:
            template = list_response.request.post_data_json
        except Exception:
            template = None
        if not isinstance(template, dict):
            raise AdapterError('No se pudo reutilizar el cuerpo autenticado de VehicleLogs.')

        headers = {
            key: value for key, value in list_response.request.headers.items()
            if key.casefold() in cls.safe_headers
        }
        records = []
        seen = set()

        def append_rows(rows):
            added = 0
            for row in rows:
                if not isinstance(row, dict):
                    continue
                identity = str(row.get('GUID') or json.dumps(row, sort_keys=True, ensure_ascii=False))
                if identity in seen:
                    continue
                seen.add(identity)
                records.append(row)
                added += 1
            return added

        append_rows(first_rows)
        pages = math.ceil(total / page_size) if total else 0
        for page_index in range(2, pages + 1):
            payload = deepcopy(template)
            changed_index, changed_size = cls._set_paging(payload, page_index, page_size)
            if not changed_index or not changed_size:
                raise AdapterError('El formato de paginación VehicleLogs no fue reconocido.')
            response = context.request.fetch(
                list_response.url,
                method='POST',
                headers=headers,
                data=json.dumps(payload, ensure_ascii=False),
                timeout=120_000,
                fail_on_status_code=False,
            )
            if response.status != 200:
                raise AdapterError(f'HikCentral rechazó la página ANPR {page_index}.')
            _meta, rows = cls._vehicle_list(response.json())
            if rows and append_rows(rows) == 0:
                raise AdapterError('HikCentral repitió una página ANPR; no se generó un archivo incompleto.')

        if len(records) != total:
            raise AdapterError(
                f'HikCentral informó {total} registros, pero entregó {len(records)}; no se envió la diferencia.'
            )
        wrong_day = [row for row in records if str(row.get('PassTime') or '')[:10] != day.isoformat()]
        if wrong_day:
            raise AdapterError('HikCentral entregó registros fuera del día solicitado; no se envió el archivo.')
        source = Path(folder) / f'ANPR_HikCentral_{day:%Y%m%d}000000_{day:%Y%m%d}235959.xlsx'
        cls._write_excel(source, records)
        return source, {
            'adapter': cls.name,
            'count': total,
            'pages': pages,
            'date': day.isoformat(),
        }

    @staticmethod
    def _write_excel(path, records):
        from openpyxl import Workbook

        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet('ANPR')
        sheet.append([
            'Hora', 'Número de matrícula', 'Cámara', 'Color del vehículo',
            'Tipo de vehículo', 'ID del recurso', 'Dirección', 'GUID',
        ])
        for row in records:
            values = [
                row.get('PassTime', ''),
                row.get('CombinePlateLicense') or row.get('PlateLicense') or 'Unknown',
                row.get('ResourceName', ''),
                row.get('VehicleColor', ''),
                row.get('VehicleType', ''),
                row.get('ResourceID', ''),
                row.get('VehicleDirectionType', ''),
                row.get('GUID', ''),
            ]
            # HikCentral's native workbooks expose textual cells. Keeping that
            # contract also prevents numeric enum values from becoming headers
            # while the portal probes alternate header rows.
            sheet.append(['' if value is None else str(value) for value in values])
        workbook.save(path)


NETWORK_ADAPTERS = (BumblebeeVehicleLogsAdapter,)


def capture_kind(response, origin):
    for adapter in NETWORK_ADAPTERS:
        kind = adapter.classify(response, origin)
        if kind:
            return adapter, kind
    return None, None
