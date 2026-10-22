from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def completed_days(first, last, timezone_name, limit=31):
    """Return an inclusive, bounded range containing only completed local days."""
    try:
        start = first if isinstance(first, date) else date.fromisoformat(str(first).strip())
        end = last if isinstance(last, date) else date.fromisoformat(str(last).strip())
    except ValueError:
        raise ValueError('Use fechas con formato AAAA-MM-DD.') from None
    if end < start:
        raise ValueError('La fecha Hasta no puede ser anterior a Desde.')
    count = (end - start).days + 1
    if count > limit:
        raise ValueError(f'Seleccione un máximo de {limit} días por envío.')
    if end >= datetime.now(ZoneInfo(timezone_name)).date():
        raise ValueError('Seleccione únicamente días terminados.')
    return [start + timedelta(days=index) for index in range(count)]
