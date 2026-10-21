"""Download HikCentral's own Excel export using its installed web client."""
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import time
from zoneinfo import ZoneInfo

from relleno.storage import ROOT, read_secret
from relleno.hikcentral import check, normalize_url
from relleno.anpr import Outbox, file_hash


class ExportError(ValueError):
    pass


def export_key(config, day):
    return hashlib.sha256(json.dumps([str(config['binding']['centre_id']), config['hikcentral']['url'], day.isoformat()], separators=(',', ':')).encode()).hexdigest()[:16]


def export_day(config, day):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    zone = ZoneInfo(config.get('timezone', 'America/Santiago'))
    if day >= datetime.now(zone).date():
        raise ExportError('Seleccione un día terminado para ANPR.')
    if not config.get('binding'):
        raise ExportError('Vincule primero este equipo al centro.')
    settings = config.get('hikcentral', {})
    credentials = read_secret('hikcentral')
    if not credentials or credentials.get('method') != 'username':
        raise ExportError('Guarde el usuario y la contraseña de HikCentral para usar su exportación web.')
    folder = ROOT / 'exports' / export_key(config, day)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / 'manifest.json'
    box = Outbox()
    with box.sender_lock('export.lock'):
        if manifest.exists():
            data = json.loads(manifest.read_text(encoding='utf-8'))
            if data.get('timezone') != config.get('timezone', 'America/Santiago'):
                raise ExportError('La zona horaria cambió. Revise el intervalo de la exportación conservada antes de repetirlo.')
            source = folder / data['filename']
            if source.is_file() and file_hash(source) == data['sha256']:
                return source
            raise ExportError('La exportación guardada cambió o falta. Revise los datos locales antes de repetirla.')
        try:
            check(settings)  # Verify the local certificate pin before reading/sending credentials.
        except ValueError:
            raise ExportError('No se pudo verificar la conexión HTTPS con HikCentral.') from None
        try:
            source, evidence = download(config, day, credentials, folder)
        except ExportError:
            raise
        except Exception:
            # Playwright exceptions can include the value passed to fill(password).
            # Never expose, log or serialize their text or tracebacks.
            raise ExportError('HikCentral no completó la exportación. Revise conexión, permisos y su interfaz web.') from None
        data = {'date':day.isoformat(), 'filename':source.name, 'sha256':file_hash(source),
                'centre_id':str(config['binding']['centre_id']), 'created':time.time(),
                'timezone':config.get('timezone', 'America/Santiago'), 'evidence':evidence}
        temporary = manifest.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(manifest)
        return source


def visible_text(page, names):
    patterns = [r'[\s\xa0]+'.join(re.escape(word) for word in name.split()) for name in names]
    return page.get_by_text(re.compile('^(?:' + '|'.join(patterns) + ')$')).filter(visible=True)


def download(config, day, credentials, folder):
    from playwright.sync_api import sync_playwright
    settings = config['hikcentral']
    url = normalize_url(settings['url'])
    with sync_playwright() as playwright:
        # Use the Windows-installed Edge; never install a second browser.
        with playwright.chromium.launch(channel='msedge', headless=True) as browser:
            # The certificate pin was verified by check() immediately before opening Edge.
            context = browser.new_context(ignore_https_errors=bool(settings.get('certificate_sha256')),
                                          timezone_id=config.get('timezone', 'America/Santiago'),
                                          viewport={'width':1440, 'height':1000}, accept_downloads=True)
            page = context.new_page()
            page.set_default_timeout(15000)
            page.goto(url + '/', wait_until='networkidle', timeout=60000)
            for selector, value in [('#username', credentials['account']), ('#password', credentials['secret'])]:
                entry = page.locator(selector)
                entry.click()
                entry.fill(value)
            page.get_by_role('button', name=re.compile('^(Iniciar sesión|Log In|Login|Log in)$')).click()
            try:
                page.wait_for_url('**/portal', timeout=30000)
            except Exception:
                raise ExportError('HikCentral no aceptó el inicio de sesión. No se repitió la contraseña.') from None
            visible_text(page, ['ANPR']).first.click()
            tree_root = visible_text(page, ['HikCentral Professional']).first
            tree_root.wait_for()
            # A first-use tooltip can cover the source selection.
            tooltip = page.get_by_role('button', name='OK', exact=True).filter(visible=True)
            if tooltip.count():
                tooltip.first.click()
            tree_root.locator('xpath=../..').locator('[treenode_check]').first.click()
            page.get_by_placeholder(re.compile(r'^(Por favor, seleccione\.|Please select\.)$')).filter(visible=True).first.click()
            visible_text(page, ['Personalizado', 'Custom']).first.click()
            range_inputs = page.locator('input.el-range-input').filter(visible=True)
            if range_inputs.count() != 2:
                raise ExportError('La interfaz de fechas de HikCentral cambió. No se exportó un intervalo distinto.')
            start = day.strftime('%Y/%m/%d') + ' 00:00:00'
            end = day.strftime('%Y/%m/%d') + ' 23:59:59'
            for entry, value in zip(range_inputs.all(), (start, end)):
                entry.fill(value)
                entry.press('Tab')
            # Clicking outside commits the native date widget.
            page.get_by_text(re.compile('^(Tiempo|Time)$')).filter(visible=True).first.click()
            if [entry.input_value() for entry in range_inputs.all()] != [start, end]:
                raise ExportError('HikCentral no conservó las fechas solicitadas; no se exportó otro intervalo.')
            with page.expect_response(lambda r: '/VehicleLogsCount' in r.url and r.request.method == 'POST', timeout=30000) as count_response:
                page.get_by_role('button', name=re.compile('^(Buscar|Search)$')).click()
            response = count_response.value
            if response.status != 200:
                raise ExportError('La consulta ANPR falló. No se sustituyó por cero.')
            evidence = response.json()
            (folder / 'search-count.json').write_text(json.dumps(evidence, ensure_ascii=False), encoding='utf-8')
            export = visible_text(page, ['Exportar', 'Export']).first
            export.click()
            dialog = page.locator('[role=dialog]:visible')
            # Verify Excel and no pictures: retain the native row export only.
            excel = dialog.locator('input[type=radio][value="0"]')
            if not excel.is_checked():
                dialog.get_by_text('Excel', exact=True).click()
            pictures = dialog.locator('input[type=checkbox]')
            if pictures.count() and pictures.first.is_checked():
                pictures.first.uncheck(force=True)
            dialog.locator('input[type=password]').fill(credentials['secret'])
            with page.expect_download(timeout=180000) as capture:
                dialog.get_by_role('button', name=re.compile('^(Guardar|Save)$')).click()
            download = capture.value
            filename = Path(download.suggested_filename).name
            expected = day.strftime('%Y%m%d') + '000000_' + day.strftime('%Y%m%d') + '235959'
            if expected not in filename or Path(filename).suffix.lower() != '.xlsx':
                raise ExportError('La descarga no corresponde al día solicitado o no es Excel. No se envió.')
            source = folder / filename
            download.save_as(str(source))
            if download.failure() or not source.exists() or source.stat().st_size == 0:
                raise ExportError('HikCentral no terminó de descargar el archivo original.')
            return source, evidence


def pending_days(config, now=None):
    zone = ZoneInfo(config.get('timezone', 'America/Santiago'))
    now = now.astimezone(zone) if now is not None else datetime.now(zone)
    # Let the previous day finish before scheduling its original export.
    last = now.date() - timedelta(days=1 if now.hour >= 1 else 2)
    first = date.fromisoformat(config['anpr'].get('export_since', last.isoformat()))
    return [first + timedelta(days=i) for i in range(max(0, (last-first).days+1))]
