"""Download HikCentral's own Excel export using its installed web client."""
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit, urlunsplit
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


def first_visible(root, selectors):
    for selector in selectors:
        matches = root.locator(selector)
        for index in range(matches.count()):
            candidate = matches.nth(index)
            if candidate.is_visible():
                return candidate
    return None


def login_controls(page, timeout_ms=30000):
    username_selectors = (
        '#username',
        'input[name="username"]',
        'input[name*="user" i]',
        'input[autocomplete="username"]',
        'input[type="text"]',
        'input:not([type])',
    )
    password_selectors = (
        '#password',
        'input[name="password"]',
        'input[name*="pass" i]',
        'input[autocomplete="current-password"]',
        'input[type="password"]',
    )
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        for frame in page.frames:
            try:
                password = first_visible(frame, password_selectors)
                username = first_visible(frame, username_selectors)
            except Exception:
                # HikCentral replaces frames while its single-page app starts.
                continue
            if username is not None and password is not None:
                return frame, username, password
        page.wait_for_timeout(250)
    raise ExportError(
        'HikCentral cargó, pero no mostró su formulario de acceso. Revise que la URL abra el portal web y no OpenAPI.'
    )


def safe_url(value):
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname or ''
        if parsed.port:
            host += f':{parsed.port}'
        return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    except (TypeError, ValueError):
        return ''


def save_web_diagnostic(progress, error):
    page = progress.get('page')
    if page is None:
        return None
    folder = ROOT / 'diagnostics'
    folder.mkdir(parents=True, exist_ok=True)
    report = {
        'stage': progress.get('message'),
        'error_type': type(error).__name__,
        'page_url': safe_url(getattr(page, 'url', '')),
        'title': '',
        'frames': [],
    }
    if progress.get('phase') == 'login_form':
        try:
            page.screenshot(path=str(folder / 'hikcentral-login.png'), full_page=True, timeout=5000)
        except Exception:
            report['screenshot_incomplete'] = True
    try:
        report['title'] = page.title()
        for frame in page.frames:
            fields = []
            inputs = frame.locator('input')
            for index in range(min(inputs.count(), 30)):
                item = inputs.nth(index)
                fields.append({
                    'type': item.get_attribute('type') or '',
                    'id': item.get_attribute('id') or '',
                    'name': item.get_attribute('name') or '',
                    'placeholder': item.get_attribute('placeholder') or '',
                    'visible': item.is_visible(),
                })
            report['frames'].append({'url': safe_url(frame.url), 'inputs': fields})
    except Exception:
        report['inspection_incomplete'] = True
    target = folder / 'hikcentral-web.json'
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def download(config, day, credentials, folder):
    progress = {'message': 'No se pudo iniciar Microsoft Edge para abrir HikCentral.'}
    try:
        return _download(config, day, credentials, folder, progress)
    except ExportError as exc:
        diagnostic = save_web_diagnostic(progress, exc)
        suffix = ' Use Exportar diagnóstico en la pestaña Cámaras.' if diagnostic else ''
        raise ExportError(str(exc) + suffix) from None
    except Exception as exc:
        # Browser exceptions may contain selectors, page content or entered values.
        diagnostic = save_web_diagnostic(progress, exc)
        suffix = ' Use Exportar diagnóstico en la pestaña Cámaras.' if diagnostic else ''
        raise ExportError(progress['message'] + suffix) from None


def _download(config, day, credentials, folder, progress):
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
            progress['page'] = page
            page.set_default_timeout(15000)
            progress['message'] = 'HikCentral no terminó de cargar su página de inicio.'
            page.goto(url + '/', wait_until='domcontentloaded', timeout=60000)
            progress['message'] = 'No se encontraron los campos de usuario y contraseña de HikCentral.'
            progress['phase'] = 'login_form'
            try:
                login_frame, username, password = login_controls(page)
            except Exception as exc:
                # Capture while the browser context is still open.
                save_web_diagnostic(progress, exc)
                raise
            progress['phase'] = 'authenticated'
            username.fill(credentials['account'])
            password.fill(credentials['secret'])
            progress['message'] = 'No se encontró el botón de inicio de sesión de HikCentral.'
            login = login_frame.get_by_role(
                'button', name=re.compile(r'^(Iniciar sesi[oó]n|Ingresar|Log In|Login|Log in|Sign In)$', re.I)
            ).or_(login_frame.locator('button[type="submit"], input[type="submit"], .login-btn, .login-button')).filter(visible=True).first
            login.click()
            progress['message'] = 'HikCentral no aceptó el inicio de sesión. Revise usuario, contraseña y permisos.'
            try:
                password.wait_for(state='hidden', timeout=30000)
            except Exception:
                raise ExportError('HikCentral no aceptó el inicio de sesión. No se repitió la contraseña.') from None
            progress['message'] = 'No se encontró el módulo ANPR en la cuenta de HikCentral.'
            visible_text(page, ['ANPR']).first.click()
            progress['message'] = 'No se pudo seleccionar el origen de cámaras ANPR en HikCentral.'
            tree_root = visible_text(page, ['HikCentral Professional']).first
            tree_root.wait_for()
            # A first-use tooltip can cover the source selection.
            tooltip = page.get_by_role('button', name='OK', exact=True).filter(visible=True)
            if tooltip.count():
                tooltip.first.click()
            tree_root.locator('xpath=../..').locator('[treenode_check]').first.click()
            progress['message'] = 'No se pudo abrir el selector de fechas de HikCentral.'
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
            progress['message'] = 'HikCentral no respondió a la búsqueda ANPR del día solicitado.'
            with page.expect_response(lambda r: '/VehicleLogsCount' in r.url and r.request.method == 'POST', timeout=30000) as count_response:
                page.get_by_role('button', name=re.compile('^(Buscar|Search)$')).click()
            response = count_response.value
            if response.status != 200:
                raise ExportError('La consulta ANPR falló. No se sustituyó por cero.')
            evidence = response.json()
            (folder / 'search-count.json').write_text(json.dumps(evidence, ensure_ascii=False), encoding='utf-8')
            progress['message'] = 'No se pudo abrir el diálogo de exportación ANPR de HikCentral.'
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
            progress['message'] = 'HikCentral no terminó de generar o descargar el Excel ANPR.'
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
