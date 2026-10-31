"""Download HikCentral's own Excel export using its installed web client."""
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import time
import traceback
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from relleno.storage import ROOT, save
from relleno.hikcentral import check, normalize_url, read_certificate_fingerprint
from relleno.managed_hikcentral import apply as apply_managed_hikcentral
from relleno.managed_hikcentral import credential_options, credentials as managed_credentials
from relleno.platform_support import browser_launch_kwargs

# Alias conservado para pruebas y extensiones antiguas; en producción resuelve
# exclusivamente las credenciales incluidas en el instalador.
read_secret = managed_credentials
from relleno.anpr import Outbox, file_hash


class ExportError(ValueError):
    pass


# HikCentral changes labels and request routes between releases while keeping
# the same workflow. Unknown layouts stop with diagnostics instead of exporting
# a different view or date range.
HIKCENTRAL_UI = {
    'module': ('ANPR', 'Vehículo', 'Vehicle', 'Vehículos', 'Vehicles'),
    'search_view': ('Búsqueda de paso de vehículos', 'Búsqueda de vehículos',
                    'Vehicle Passing Search', 'Vehicle Search'),
    'root': ('HikCentral Professional', 'Todos los recursos', 'All Resources', 'All Cameras'),
    'time': ('Tiempo', 'Hora', 'Time'),
    'custom': ('Personalizado', 'Personalizada', 'Custom', 'Customize'),
    'export': ('Exportar', 'Export'),
    'file_format': ('Formato de archivo', 'File Format', 'Export Format'),
}
ANPR_COUNT_RESPONSE = re.compile(
    r'VehicleLogsCount|vehicle[^/?]*(?:count|total)|passing[^/?]*(?:count|total)|anpr[^/?]*(?:count|total)',
    re.I,
)


def export_key(config, day):
    apply_managed_hikcentral(config)
    return hashlib.sha256(json.dumps([str(config['binding']['centre_id']), config['hikcentral']['url'], day.isoformat()], separators=(',', ':')).encode()).hexdigest()[:16]


def export_day(config, day):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    zone = ZoneInfo(config.get('timezone', 'America/Santiago'))
    if day >= datetime.now(zone).date():
        raise ExportError('Seleccione un día terminado para ANPR.')
    if not config.get('binding'):
        raise ExportError('Vincule primero este equipo al centro.')
    apply_managed_hikcentral(config)
    settings = config['hikcentral']
    credentials = read_secret()
    if credentials.get('secrets'):
        try:
            fingerprint = read_certificate_fingerprint(settings['url'])
        except ValueError as exc:
            raise ExportError(str(exc)) from None
        if settings.get('certificate_sha256') != fingerprint:
            settings['certificate_sha256'] = fingerprint
            save(config)
    folder = ROOT / 'exports' / export_key(config, day)
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / 'manifest.json'
    box = Outbox()
    with box.sender_lock('export.lock'):
        if manifest.exists():
            previous = json.loads(manifest.read_text(encoding='utf-8'))
            if previous.get('evidence', {}).get('adapter'):
                # Preserve the old generated file, manifest and receipt for audit.
                # Repeated requests now reuse a separate original native export.
                folder = folder / 'native-excel'
                folder.mkdir(parents=True, exist_ok=True)
                manifest = folder / 'manifest.json'
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


def ui_text(page, key):
    return visible_text(page, HIKCENTRAL_UI[key])


def date_range_contains_day(page, day):
    """Detecta el rango ya aplicado aunque HikCentral cierre el calendario solo."""
    markers = (day.strftime('%Y/%m/%d'), day.strftime('%Y-%m-%d'))
    matches = 0
    inputs = page.locator('input')
    for index in range(inputs.count()):
        field = inputs.nth(index)
        if not field.is_visible():
            continue
        try:
            value = field.input_value()
        except Exception:
            continue
        matches += max(value.count(marker) for marker in markers)
    return matches >= 2


def first_visible(root, selectors):
    for selector in selectors:
        matches = root.locator(selector)
        for index in range(matches.count()):
            candidate = matches.nth(index)
            if candidate.is_visible():
                return candidate
    return None


def login_controls(page, timeout_ms=60000, events=None):
    username_selectors = (
        '#username',
        'input[name="username"]',
        'input[name*="user" i]',
        'input[placeholder*="usuario" i]',
        'input[placeholder*="user" i]',
        'input[autocomplete="username"]',
        'input[type="text"]',
        'input:not([type])',
    )
    password_selectors = (
        '#password',
        'input[name="password"]',
        'input[name*="pass" i]',
        'input[placeholder*="contraseña" i]',
        'input[placeholder*="password" i]',
        'input[autocomplete="current-password"]',
        'input[type="password"]',
    )
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        # HikCentral puede abrir el login en otra pestaña y cerrar la original.
        pages = [item for item in page.context.pages if not item.is_closed()] or [page]
        frames = [frame for item in reversed(pages) for frame in item.frames]
        for frame in frames:
            try:
                password = first_visible(frame, password_selectors)
                username = first_visible(frame, username_selectors)
            except Exception as exc:
                # HikCentral replaces frames while its single-page app starts.
                if events is not None and len(events) < 200:
                    events.append(f'login-probe {type(exc).__name__}')
                continue
            if username is not None and password is not None:
                return frame, username, password
        time.sleep(0.25)
    raise ExportError(
        'HikCentral cargó, pero no mostró su formulario de acceso. Revise que la URL abra el portal web y no OpenAPI.'
    )


def safe_url(value):
    try:
        parsed = urlsplit(str(value))
        host = parsed.hostname or ''
        if parsed.port:
            host += f':{parsed.port}'
        return urlunsplit((parsed.scheme, host, parsed.path, '', parsed.fragment.split('?')[0][:80]))
    except (TypeError, ValueError):
        return ''


def tree_root_checked(row):
    """True si la raíz quedó marcada completa (no parcial) en cualquiera de los árboles."""
    return bool(row.evaluate("""r => {
        const input = r.querySelector('input[type=checkbox]');
        if (input) return input.checked && !input.indeterminate;
        const box = r.querySelector('[treenode_check],[class*=checkbox]');
        const cls = box && typeof box.className === 'string' ? box.className : '';
        return /checkbox_true_full|(^|\\s)(is-checked|checked)(\\s|$)/.test(cls) && !/part|indeterminate|half/.test(cls);
    }"""))


def dismiss_hikcentral_overlays(page):
    """Best-effort dismissal of first-use notices that can cover ANPR controls."""
    labels = (
        r'^(Ignorar|Ignore)$',
        r'^(No vuelva a mostrar|No mostrar de nuevo|Don.t show again)$',
        r'^(OK|Aceptar|Got it)$',
    )
    for label in labels:
        pattern = re.compile(label, re.I)
        candidates = page.get_by_role('button', name=pattern).filter(visible=True)
        if not candidates.count():
            candidates = page.get_by_text(pattern).filter(visible=True)
        for index in range(min(candidates.count(), 3)):
            try:
                candidates.nth(index).click(timeout=2000, force=True)
            except Exception:
                pass


def preferred_anpr_module(page):
    """Prefer the explicit ANPR tab over adjacent vehicle catalogues."""
    anpr = visible_text(page, ('ANPR',))
    if anpr.count():
        return anpr
    return visible_text(page, HIKCENTRAL_UI['module'][1:])


def wait_hikcentral_idle(page, timeout=15000):
    """Wait for the dashboard loading mask that can discard early tab clicks."""
    loading = page.get_by_text(
        re.compile(r'^(Cargando(?:\.\.\.)?|Loading(?:\.\.\.)?)$', re.I)
    ).filter(visible=True)
    try:
        loading.first.wait_for(state='hidden', timeout=timeout)
    except Exception:
        pass


def open_anpr_search(page, origin):
    """Open vehicle-passing search across legacy and application-registry layouts."""
    root = ui_text(page, 'root')
    for _attempt in range(3):
        wait_hikcentral_idle(page)
        dismiss_hikcentral_overlays(page)
        module = preferred_anpr_module(page)
        if not module.count():
            applications = page.locator('#navigation_addMenuBtn').filter(visible=True)
            if applications.count():
                applications.first.click()
                dismiss_hikcentral_overlays(page)
                module = preferred_anpr_module(page)
        if module.count():
            module.first.wait_for(timeout=15000)
            module.first.click(force=True)
            wait_hikcentral_idle(page)
            dismiss_hikcentral_overlays(page)
        else:
            # Legacy installations expose ANPR directly in their main navigation.
            ui_text(page, 'module').first.click(force=True)

        search = ui_text(page, 'search_view')
        try:
            search.first.wait_for(timeout=5000)
            search.first.click(force=True)
        except Exception:
            pass
        try:
            root.first.wait_for(timeout=10000)
            return
        except Exception:
            page.wait_for_timeout(1000)

    # Some catalogues open registered vehicles instead of passing search.
    page.goto(origin.rstrip('/') + '/#/anpr/vehicleSearch',
              wait_until='domcontentloaded', timeout=60000)
    wait_hikcentral_idle(page)
    dismiss_hikcentral_overlays(page)
    ui_text(page, 'root').first.wait_for(timeout=30000)


def select_all_anpr_cameras(page, row, attempts=16):
    """Espera el árbol y cierra avisos tardíos antes de marcar su raíz."""
    loading_pattern = re.compile(r'^(Cargando(?:\.\.\.)?|Loading(?:\.\.\.)?)$', re.I)
    for _attempt in range(attempts):
        dismiss_hikcentral_overlays(page)
        if tree_root_checked(row):
            return True
        loading = page.get_by_text(loading_pattern).filter(visible=True)
        if loading.count():
            page.wait_for_timeout(750)
            continue
        try:
            row.locator(
                "[treenode_check], input[type=checkbox], [class*=checkbox]"
            ).first.click(timeout=2500, force=True)
        except Exception:
            pass
        page.wait_for_timeout(750)
    dismiss_hikcentral_overlays(page)
    return tree_root_checked(row)


def type_into(field, value, progress):
    """HikCentral deja sus campos en solo lectura hasta recibir foco (evita autocompletar)."""
    field.click(timeout=5000)
    try:
        field.fill(value, timeout=5000)
    except Exception:
        progress.setdefault('events', []).append('login-field readonly; se habilita tras el foco')
        field.evaluate("e => { e.removeAttribute('readonly'); e.removeAttribute('disabled'); }")
        field.fill(value, timeout=5000)


def edge_visible():
    """Modo visible para diagnóstico: variable de entorno o archivo edge-visible.flag."""
    return os.environ.get('RELLENO_EDGE_VISIBLE') == '1' or (ROOT / 'edge-visible.flag').exists()


def watch_page(page, progress):
    """Registra eventos del navegador (sin cuerpos ni credenciales) para el diagnóstico."""
    events = progress.setdefault('events', [])
    started = time.monotonic()

    def add(kind, detail=''):
        # Tras escribir credenciales solo se registra el tipo de evento, nunca su texto.
        if progress.get('phase') == 'authenticated' and kind.split('.')[0] in ('console', 'pageerror', 'dialog'):
            detail = ''
        if len(events) < 200:
            events.append(f'{time.monotonic() - started:6.1f}s {kind} {str(detail)[:160]}')

    page.on('console', lambda m: m.type in ('error', 'warning') and add('console.' + m.type, m.text))
    page.on('pageerror', lambda e: add('pageerror', e))
    page.on('crash', lambda _p: add('crash'))
    page.on('close', lambda _p: add('close'))
    page.on('requestfailed', lambda r: add('requestfailed', f'{safe_url(r.url)} {r.failure or ""}'))
    page.on('response', lambda r: r.status >= 400 and add(f'http{r.status}', safe_url(r.url)))
    page.on('domcontentloaded', lambda _p: add('domcontentloaded'))
    page.on('load', lambda _p: add('load'))

    def on_dialog(dialog):
        add('dialog.' + dialog.type, dialog.message)
        try:
            dialog.dismiss()
        except Exception:
            pass
    page.on('dialog', on_dialog)


def save_web_diagnostic(progress, error):
    page = progress.get('page')
    if page is None:
        return None
    if progress.get('diagnostic'):
        # Ya se guardó con el navegador abierto; no sobrescribir con la página cerrada.
        return progress['diagnostic']
    folder = Path(progress.get('diagnostic_folder') or ROOT / 'diagnostics')
    folder.mkdir(parents=True, exist_ok=True)
    from relleno.portal import CLIENT_VERSION
    report = {
        'client_version': CLIENT_VERSION,
        'browser_mode': ('edge-visible' if edge_visible() else 'edge-offscreen') + ' sin-webgl',
        'stage': progress.get('message'),
        'where': [f'{Path(item.filename).name}:{item.name}:{item.lineno}' for item in traceback.extract_tb(error.__traceback__)][-8:],
        'events': list(progress.get('events') or [])[-120:],
        'error_type': type(error).__name__,
        'page_url': safe_url(getattr(page, 'url', '')),
        'title': '',
        'frames': [],
    }
    if True:  # Captura en cualquier etapa: muestra qué veía Edge al fallar.
        try:
            diagnostic_checkpoint(progress, 'error')
        except Exception:
            report['screenshot_incomplete'] = True
    if progress.get('phase') == 'authenticated' and not progress.get('diagnostic_mode'):
        try:
            # Textos cortos de menús y botones visibles (sin valores de campos).
            report['visible_texts'] = page.evaluate("""() => {
                const out = new Set();
                for (const el of document.querySelectorAll('a,button,li,span,div,[role=menuitem],[role=tab]')) {
                    if (out.size >= 120 || el.children.length > 0) continue;
                    const text = (el.innerText || '').trim().replace(/\\s+/g, ' ');
                    const box = el.getBoundingClientRect();
                    if (text && text.length <= 40 && box.width > 0 && box.height > 0) out.add(text);
                }
                return [...out];
            }""")
        except Exception:
            report['visible_texts_incomplete'] = True
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
    progress['diagnostic'] = target
    return target


def diagnostic_checkpoint(progress, stage):
    """Capture UI evidence without field values, plates, images or video."""
    if not progress.get('diagnostic_mode') and stage != 'error':
        return None
    page = progress.get('page')
    if page is None or page.is_closed():
        return None
    folder = Path(progress.get('diagnostic_folder') or ROOT / 'diagnostics')
    folder.mkdir(parents=True, exist_ok=True)
    index = len(progress.setdefault('checkpoints', [])) + 1
    safe_stage = re.sub(r'[^a-z0-9-]+', '-', str(stage).casefold()).strip('-')[:40] or 'step'
    screenshot = folder / f'{index:02d}-{safe_stage}.png'
    marker = 'relleno-diagnostic-redaction'
    try:
        controls = page.evaluate(r"""() => {
            const clean = value => (value || '').trim().replace(/\s+/g, ' ').slice(0, 80);
            return [...document.querySelectorAll('button,a,[role=button],[role=menuitem],[role=tab],label')]
                .filter(el => { const b=el.getBoundingClientRect(); return b.width>0 && b.height>0; })
                .slice(0, 160)
                .map(el => ({tag:el.tagName.toLowerCase(), role:el.getAttribute('role') || '', text:clean(el.innerText)}));
        }""")
    except Exception:
        controls = []
    try:
        page.evaluate("""id => {
            document.getElementById(id)?.remove();
            const style=document.createElement('style'); style.id=id;
            style.textContent=`input,textarea{color:transparent!important;text-shadow:none!important}
                tbody,[role=rowgroup],[class*=result-list],[class*=vehicle-list],img,video,canvas{filter:blur(12px)!important}`;
            document.documentElement.appendChild(style);
        }""", marker)
        page.screenshot(path=str(screenshot), full_page=False, timeout=7000)
    except Exception:
        screenshot = None
    finally:
        try:
            page.evaluate("id => document.getElementById(id)?.remove()", marker)
        except Exception:
            pass
    item = {
        'index': index,
        'stage': str(stage),
        'message': str(progress.get('message') or ''),
        'url': safe_url(getattr(page, 'url', '')),
        'title': page.title() if not page.is_closed() else '',
        'screenshot': screenshot.name if screenshot else None,
        'controls': controls,
    }
    progress['checkpoints'].append(item)
    (folder / 'steps.json').write_text(
        json.dumps(progress['checkpoints'], ensure_ascii=False, indent=2), encoding='utf-8'
    )
    return item


def download(config, day, credentials, folder, diagnostic_folder=None):
    options = credential_options(credentials)
    if not options:
        raise ExportError('La instalación no contiene credenciales de HikCentral.')
    for index, option in enumerate(options):
        progress = {
            'message': 'No se pudo iniciar Microsoft Edge para abrir HikCentral.',
            'diagnostic_mode': diagnostic_folder is not None,
            'diagnostic_folder': str(diagnostic_folder) if diagnostic_folder else None,
        }
        try:
            return _download(config, day, option, folder, progress)
        except ExportError as exc:
            auth_failure = str(exc).startswith('HikCentral no aceptó el inicio de sesión')
            if auth_failure and index + 1 < len(options):
                continue
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
        # Use the browser already installed by the operating system. Normal mode
        # con la ventana fuera de pantalla: el login de
        # HikCentral se congela en modo headless, igual que en un PC sin GPU.
        visible = edge_visible()
        window = ['--window-position=40,40'] if visible else ['--window-position=-32000,-32000']
        # Sin GPU, el fondo 3D del login de HikCentral puede dejar la página sin responder.
        launch = browser_launch_kwargs(headless=False)
        with playwright.chromium.launch(**launch,
                                        args=[*window, '--window-size=1440,1000',
                                              '--disable-3d-apis', '--disable-webgl']) as browser:
            # The certificate pin was verified by check() immediately before opening Edge.
            context = browser.new_context(ignore_https_errors=bool(settings.get('certificate_sha256')),
                                          timezone_id=config.get('timezone', 'America/Santiago'),
                                          viewport={'width':1440, 'height':1000}, accept_downloads=True,
                                          service_workers='block')
            page = context.new_page()
            progress['page'] = page
            watch_page(page, progress)

            def follow(new_page):
                progress.setdefault('events', []).append(f'newpage {safe_url(new_page.url)}')
                progress['page'] = new_page
                watch_page(new_page, progress)
            context.on('page', follow)
            try:
                page.set_default_timeout(15000)
                progress['message'] = 'HikCentral no terminó de cargar su página de inicio.'
                page.goto(url + '/#/', wait_until='domcontentloaded', timeout=60000)
                progress['message'] = 'No se encontraron los campos de usuario y contraseña de HikCentral.'
                progress['phase'] = 'login_form'
                try:
                    login_frame, username, password = login_controls(page, events=progress.setdefault('events', []))
                    page = login_frame.page
                    progress['page'] = page
                    diagnostic_checkpoint(progress, 'login-detectado')
                except Exception as exc:
                    # Capture while the browser context is still open.
                    save_web_diagnostic(progress, exc)
                    raise
                progress['phase'] = 'authenticated'
                progress['message'] = 'No se pudo escribir en los campos de acceso de HikCentral.'
                try:
                    type_into(username, credentials['account'], progress)
                    type_into(password, credentials['secret'], progress)
                except Exception as exc:
                    save_web_diagnostic(progress, exc)
                    raise
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
                diagnostic_checkpoint(progress, 'sesion-iniciada')
                progress['message'] = 'No se encontró el módulo ANPR en la cuenta de HikCentral.'
                open_anpr_search(page, url)
                diagnostic_checkpoint(progress, 'modulo-anpr')
                progress['message'] = 'No se pudo seleccionar el origen de cámaras ANPR en HikCentral.'
                root = ui_text(page, 'root').first
                root.wait_for(timeout=30000)
                dismiss_hikcentral_overlays(page)
                # Fila de la raíz: el ancestro más cercano que contiene su casilla (árbol zTree o el de la versión nueva).
                row = root.locator("xpath=ancestor::*[.//*[@treenode_check or @type='checkbox' or contains(@class,'checkbox')]][1]")
                if not select_all_anpr_cameras(page, row):
                    raise ExportError('HikCentral no marcó todas las cámaras ANPR; no se exportó una selección parcial.')
                diagnostic_checkpoint(progress, 'camaras-seleccionadas')
                progress['message'] = 'No se pudo abrir el selector de fechas de HikCentral.'
                placeholder = page.get_by_placeholder(re.compile(r'^(Por favor, seleccione\.|Please select\.)$')).filter(visible=True)
                if placeholder.count():
                    placeholder.first.click()
                else:
                    # Versión nueva: el selector muestra "Hoy"; es el primer campo bajo "Tiempo".
                    ui_text(page, 'time').first.locator('xpath=following::input[1]').click()
                ui_text(page, 'custom').first.click()
                range_inputs = page.locator('input.el-range-input').filter(visible=True)
                if range_inputs.count() != 2:
                    raise ExportError('La interfaz de fechas de HikCentral cambió. No se exportó un intervalo distinto.')
                start = day.strftime('%Y/%m/%d') + ' 00:00:00'
                end = day.strftime('%Y/%m/%d') + ' 23:59:59'
                for entry, value in zip(range_inputs.all(), (start, end)):
                    entry.fill(value)
                    entry.press('Tab')
                accept = page.get_by_role('button', name=re.compile(r'^(Aceptar|OK|Confirmar|Confirm)$')).filter(visible=True)
                if accept.count():
                    try:
                        # Algunas versiones aplican el segundo extremo y desmontan
                        # el calendario durante este click. El rango visible es la
                        # confirmación autoritativa en ese caso.
                        accept.first.click(timeout=2500, force=True)
                    except Exception:
                        if not date_range_contains_day(page, day):
                            raise
                else:
                    # Clicking outside commits the native date widget.
                    ui_text(page, 'time').first.click()
                if not date_range_contains_day(page, day):
                    raise ExportError('HikCentral no conservó las fechas solicitadas; no se exportó otro intervalo.')
                diagnostic_checkpoint(progress, 'fecha-configurada')
                progress['message'] = 'HikCentral no respondió a la búsqueda ANPR del día solicitado.'
                with page.expect_response(lambda r: r.request.method == 'POST' and ANPR_COUNT_RESPONSE.search(r.url), timeout=30000) as count_response:
                    page.get_by_role('button', name=re.compile('^(Buscar|Search)$')).click()
                response = count_response.value
                if response.status != 200:
                    raise ExportError('La consulta ANPR falló. No se sustituyó por cero.')
                evidence = response.json()
                (folder / 'search-count.json').write_text(json.dumps(evidence, ensure_ascii=False), encoding='utf-8')
                diagnostic_checkpoint(progress, 'busqueda-completada')
                # Always retain HikCentral's original workbook. API enums are not
                # interchangeable with the localized values in its native export.
                progress['message'] = 'No se pudo abrir el diálogo de exportación ANPR de HikCentral.'
                export = ui_text(page, 'export').first
                export.click()
                dialog = page.locator('[role=dialog]:visible')
                if not dialog.count():
                    # Versión nueva: panel lateral sin role=dialog; se toma el que contiene el formato.
                    dialog = ui_text(page, 'file_format').first.locator(
                        "xpath=ancestor::*[.//input[@type='password']][1]")
                dialog.first.wait_for(timeout=15000)
                dialog = dialog.first
                # Verify Excel and no pictures: retain the native row export only (la versión nueva parte en CSV).
                excel = dialog.locator('input[type=radio][value="0"]')
                if not excel.count() or not excel.is_checked():
                    dialog.get_by_text('Excel', exact=True).click()
                pictures = dialog.locator('input[type=checkbox]')
                if pictures.count() and pictures.first.is_checked():
                    pictures.first.uncheck(force=True)
                type_into(dialog.locator('input[type=password]').first, credentials['secret'], progress)
                progress['message'] = 'HikCentral no terminó de generar o descargar el Excel ANPR.'
                with page.expect_download(timeout=180000) as capture:
                    dialog.get_by_role('button', name=re.compile('^(Guardar|Save)$')).click()
                download = capture.value
                filename = Path(download.suggested_filename).name
                suffix = Path(filename).suffix.lower()
                if suffix == '.zip':
                    raise ExportError('HikCentral entregó un .zip en vez de un Excel. Use Exportar diagnóstico y envíelo.')
                if suffix not in ('.xlsx', '.xls'):
                    raise ExportError('La descarga de HikCentral no es Excel. No se envió.')
                # El intervalo ya se verificó en el buscador; el nombre del archivo varía entre versiones.
                source = folder / filename
                download.save_as(str(source))
                if download.failure() or not source.exists() or source.stat().st_size == 0:
                    raise ExportError('HikCentral no terminó de descargar el archivo original.')
                diagnostic_checkpoint(progress, 'excel-generado')
                return source, evidence
            except Exception as exc:
                # Captura con Edge aún abierto, en cualquier etapa del flujo.
                save_web_diagnostic(progress, exc)
                raise


def pending_days(config, now=None):
    zone = ZoneInfo(config.get('timezone', 'America/Santiago'))
    now = now.astimezone(zone) if now is not None else datetime.now(zone)
    # Let the previous day finish before scheduling its original export.
    last = now.date() - timedelta(days=1 if now.hour >= 1 else 2)
    first = date.fromisoformat(config['anpr'].get('export_since', last.isoformat()))
    return [first + timedelta(days=i) for i in range(max(0, (last-first).days+1))]
