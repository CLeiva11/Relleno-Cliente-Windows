import json
import os
import queue
import socket
import threading
import time
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import ttk, messagebox, filedialog
from zoneinfo import ZoneInfo

from relleno.storage import ROOT, load, save, read_secret, store_secret
from relleno.portal import link, persist_binding, PortalError
from relleno.cameras import probe, parse_inventory, extract_day, CameraError
from relleno.anpr import Outbox, AnprError
from relleno.hcp_export import ExportError
from relleno.date_ranges import completed_days


class App:
    def __init__(self, root):
        self.root = root
        self.config = load()
        if not self.config.get('binding'):
            recovery = read_secret('portal-recovery')
            if recovery:
                self.config = persist_binding(recovery)
        self.outbox = Outbox()
        root.title('Relleno Cliente · Comprobaciones')
        root.geometry('1060x740')
        root.minsize(840, 620)
        self.events = queue.Queue()
        self.busy = False
        self.status_text = tk.StringVar(value='Listo')
        tabs = ttk.Notebook(root)
        tabs.pack(fill='both', expand=True, padx=14, pady=14)
        for name, builder in [('Inicio', self.home), ('ANPR', self.anpr), ('Cámaras', self.cameras), ('Conteos', self.counts), ('HikCentral', self.hikcentral)]:
            frame = ttk.Frame(tabs, padding=14)
            tabs.add(frame, text=name)
            builder(frame)
        ttk.Label(root, textvariable=self.status_text, wraplength=1000).pack(anchor='w', padx=16, pady=(0, 10))
        self.refresh()
        if self.config.get('binding'):
            tabs.select(1)
        self.refresh_anpr()
        root.after(100, self.poll)

    def field(self, parent, label, value='', secret=False, choices=None):
        ttk.Label(parent, text=label).pack(anchor='w', pady=(7, 2))
        var = tk.StringVar(value=value)
        widget = ttk.Combobox(parent, textvariable=var, values=choices, state='readonly') if choices else ttk.Entry(parent, textvariable=var, show='•' if secret else '')
        widget.pack(fill='x')
        return var

    def action_menu(self, parent, items, text='Más acciones'):
        button = ttk.Menubutton(parent, text=text)
        menu = tk.Menu(button, tearoff=False)
        for label, command in items:
            if label is None:
                menu.add_separator()
            else:
                menu.add_command(label=label, command=command)
        button.configure(menu=menu)
        return button

    def guarded(self, action):
        try:
            action()
        except (ValueError, OSError) as exc:
            messagebox.showerror('Revise la configuración', str(exc))

    def poll(self):
        try:
            while True:
                action = self.events.get_nowait()
                action()
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def background(self, title, work, done):
        if self.busy:
            messagebox.showinfo('Operación en curso', 'Espere a que termine la operación actual.')
            return
        self.busy = True
        self.status_text.set(title)
        def completed(result=None, error=None):
            self.busy = False
            if error:
                self.status_text.set(error)
                messagebox.showerror('No se pudo completar', error)
            else:
                try:
                    done(result)
                    self.status_text.set('Operación terminada')
                except Exception:
                    self.status_text.set('No se pudo guardar el resultado. Revise los permisos locales.')
                    messagebox.showerror('Guardado pendiente', 'No se pudo guardar el resultado. La respuesta de vinculación, si existe, permanece protegida para recuperarla al abrir de nuevo.')
        def run():
            try:
                result = work()
                self.events.put(lambda: completed(result=result))
            except (PortalError, CameraError, AnprError, ExportError, ValueError) as exc:
                error = str(exc)
                self.events.put(lambda message=error: completed(error=message))
            except Exception:
                self.events.put(lambda: completed(error='No se pudo completar. Revise configuración, permisos y conexión. No se muestran respuestas que puedan contener secretos.'))
        threading.Thread(target=run, daemon=True).start()

    def home(self, frame):
        self.centre_label = ttk.Label(frame, font=('Segoe UI', 14), wraplength=950)
        self.centre_label.pack(anchor='w', pady=(0, 10))
        self.channel_label = ttk.Label(frame, wraplength=950)
        self.channel_label.pack(anchor='w', pady=8)
        self.link_box = ttk.LabelFrame(frame, text='1. Vincular este equipo', padding=12)
        self.link_box.pack(fill='x', pady=10)
        code = self.field(self.link_box, 'Pegue el código nuevo de Comprobaciones', secret=True)
        def start():
            value = code.get().strip()
            if not value:
                messagebox.showerror('Falta el código', 'Genere un código nuevo en Comprobaciones y péguelo aquí.')
                return
            code.set('')
            def done(data):
                self.config = persist_binding(data)
                from relleno.anpr_worker import autostart, start
                autostart(True)
                start()
                self.refresh()
                messagebox.showinfo('Centro vinculado', 'Listo. El centro quedó fijado y el token se guardó en Windows.')
            self.background('Vinculando con el portal…', lambda: link(value, socket.gethostname()), done)
        ttk.Button(self.link_box, text='Vincular', command=start).pack(anchor='w', pady=8)
        ttk.Label(frame, text='2. Configure cámaras e HikCentral.\n3. El servicio enviará el estado y atenderá la programación y las solicitudes del portal.', wraplength=950).pack(anchor='w', pady=12)
        self.portal_status = ttk.Label(frame, text='Portal: sin comprobar', wraplength=950)
        self.portal_status.pack(anchor='w', pady=(0, 8))
        def test_portal():
            if not self.config.get('binding'):
                messagebox.showinfo('Vinculación pendiente', 'Vincule primero este equipo.')
                return
            from relleno.agent import heartbeat
            def done(data):
                self.portal_status.config(text='Portal: conectado. Última señal confirmada ' + str(data.get('seen_at') or 'ahora'))
            self.background('Comprobando conexión con el portal…', lambda: heartbeat(load()), done)
        ttk.Button(frame, text='Comprobar conexión con el portal', command=test_portal).pack(anchor='w', pady=(0, 12))
        advanced = ttk.LabelFrame(frame, text='Preferencias', padding=10)
        advanced.pack(fill='x')
        zone = self.field(advanced, 'Zona horaria', self.config.get('timezone', 'America/Santiago'), choices=('America/Santiago', 'America/Punta_Arenas', 'America/Coyhaique', 'Pacific/Easter'))
        def settings():
            ZoneInfo(zone.get())
            self.config['timezone'] = zone.get()
            save(self.config)
            self.status_text.set('Zona horaria guardada')
        ttk.Button(advanced, text='Guardar zona horaria', command=lambda: self.guarded(settings)).pack(anchor='w', pady=8)
        ttk.Button(frame, text='Abrir datos locales', command=lambda: os.startfile(str(ROOT))).pack(anchor='w', pady=14)

    def refresh(self):
        binding = self.config.get('binding')
        self.centre_label.config(text='Centro: ' + binding['centre_name'] if binding else 'Equipo sin vincular')
        if binding:
            self.link_box.pack_forget()
        channel = 'Servicio automático activo: estado, Personas y ANPR disponibles según la configuración del equipo.' if binding else 'Vincule el equipo para activar el servicio automático.'
        self.channel_label.config(text=channel)
        self.table.delete(*self.table.get_children())
        for i, camera in enumerate(self.config.get('cameras', [])):
            self.table.insert('', 'end', iid=str(i), values=[camera.get(k, '') for k in ('name', 'ip', 'location', 'model', 'connection_status')])

    def anpr(self, frame):
        ttk.Label(frame, text='Envíe los Excel originales de HikCentral a Comprobaciones. La corrección se confirma en el portal.', wraplength=980).pack(anchor='w')
        def send_files():
            if not self.config.get('binding'):
                messagebox.showinfo('Vinculación pendiente', 'Vincule este equipo desde Inicio.')
                return
            paths = filedialog.askopenfilenames(title='Exportaciones ANPR originales', filetypes=[('Excel de HikCentral', '*.xls *.xlsx *.xlsm')])
            if not paths:
                return
            config = load()
            def work():
                for path in paths:
                    self.outbox.add(path, config['binding'])
                return self.outbox.drain(config)
            self.background('Conservando originales y enviando ANPR…', work, self.anpr_result)
        export_row = ttk.Frame(frame)
        export_row.pack(fill='x', pady=10)
        yesterday = str((datetime.now(ZoneInfo(self.config['timezone']))-timedelta(days=1)).date())
        ttk.Label(export_row, text='Desde').pack(side='left')
        first_day = tk.StringVar(value=yesterday)
        ttk.Entry(export_row, textvariable=first_day, width=12).pack(side='left', padx=(6, 10))
        ttk.Label(export_row, text='Hasta').pack(side='left')
        last_day = tk.StringVar(value=yesterday)
        ttk.Entry(export_row, textvariable=last_day, width=12).pack(side='left', padx=(6, 10))
        def export():
            try:
                selected_days = completed_days(
                    first_day.get(), last_day.get(), self.config['timezone']
                )
            except ValueError as exc:
                messagebox.showerror('Rango inválido', str(exc))
                return
            config = load()
            def work():
                from relleno.anpr_schedule import export_and_enqueue
                errors = []
                for selected in selected_days:
                    try:
                        export_and_enqueue(config, selected, self.outbox)
                        self.outbox.drain(config)
                    except (ExportError, AnprError, ValueError) as exc:
                        errors.append(f'{selected}: {exc}')
                if errors:
                    raise ExportError('No se completaron todos los días. ' + ' | '.join(errors[:6]))
                return self.outbox.drain(config)
            self.background(
                f'HikCentral está preparando y enviando {len(selected_days)} día(s)…',
                work, self.anpr_result,
            )
        ttk.Button(export_row, text='Generar y enviar', command=export).pack(side='left')
        self.action_menu(export_row, [
            ('Enviar Excel manual…', send_files),
            ('Reintentar pendientes', lambda: self.background(
                'Enviando ANPR pendiente…', lambda: self.outbox.drain(), self.anpr_result
            )),
            (None, None),
            ('Abrir Comprobaciones', lambda: webbrowser.open(
                'https://siem.domoticatechnology.cl/relleno/comprobaciones/'
            )),
        ]).pack(side='left', padx=8)
        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True)
        self.anpr_table = ttk.Treeview(body, columns=('file', 'state', 'receipt'), show='headings', height=7)
        for key, title, width in zip(self.anpr_table['columns'], ('Archivo original', 'Estado', 'Comprobante'), (540, 140, 230)):
            self.anpr_table.heading(key, text=title)
            self.anpr_table.column(key, width=width)
        scroll = ttk.Scrollbar(body, orient='vertical', command=self.anpr_table.yview)
        self.anpr_table.configure(yscrollcommand=scroll.set)
        self.anpr_table.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        self.anpr_detail = ttk.Label(frame, wraplength=980)
        self.anpr_detail.pack(anchor='w', pady=8)
        def detail(event=None):
            if self.anpr_table.selection():
                row = next((row for row in self.outbox.list() if row['batch_id'] == self.anpr_table.selection()[0]), None)
                if row:
                    self.anpr_detail.config(text=row['message'])
        self.anpr_table.bind('<<TreeviewSelect>>', detail)
        settings = self.config.get('anpr', {})
        automatic = ttk.LabelFrame(frame, text='Envío automático al iniciar Windows', padding=10)
        automatic.pack(fill='x', pady=8)
        daily = tk.BooleanVar(value=settings.get('auto_export_enabled', False))
        ttk.Checkbutton(
            automatic,
            text='Enviar ANPR de HikCentral y conteos de Personas cada día terminado (a partir de la 01:00)',
            variable=daily,
        ).pack(anchor='w', pady=3)
        folder = self.field(automatic, 'Carpeta donde HikCentral guarda los Excel ANPR', settings.get('watch_folder', str(ROOT / 'Exportaciones ANPR')))
        def browse():
            value = filedialog.askdirectory(title='Carpeta de exportaciones ANPR')
            if value:
                folder.set(value)
        ttk.Button(automatic, text='Elegir carpeta', command=browse).pack(anchor='w', pady=4)
        enabled = tk.BooleanVar(value=settings.get('watch_enabled', False))
        ttk.Checkbutton(automatic, text='Enviar también los Excel ANPR nuevos de esta carpeta', variable=enabled).pack(anchor='w', pady=5)
        ttk.Label(automatic, text='Solo archivos Excel cuyo nombre contiene ANPR. No importa el historial anterior al activar esta opción.', wraplength=950).pack(anchor='w')
        def persist():
            from relleno.anpr_worker import autostart, start
            target = Path(folder.get().strip()).expanduser().resolve()
            if enabled.get() and not target.is_dir():
                raise ValueError('Seleccione una carpeta existente para las exportaciones.')
            if (enabled.get() or daily.get()) and not self.config.get('binding'):
                raise ValueError('Vincule el equipo antes de activar el envío automático.')
            previous = self.config.get('anpr', {})
            since = previous.get('watch_since_ns', time.time_ns()) if str(target) == previous.get('watch_folder') else time.time_ns()
            first = previous.get('export_since', str((datetime.now(ZoneInfo(self.config['timezone']))-timedelta(days=1)).date()))
            self.config['anpr'] = previous | {'watch_folder': str(target), 'watch_enabled': enabled.get(), 'watch_since_ns': since, 'file_pattern':'*ANPR*', 'auto_export_enabled':daily.get(), 'export_since':first}
            people = self.config.get('people', {})
            people_first = people.get('export_since', first)
            self.config['people'] = people | {
                'auto_export_enabled': daily.get() and bool(self.config.get('cameras')),
                'export_since': people_first,
            }
            save(self.config)
            active = bool(self.config.get('binding'))
            autostart(active)
            if active:
                start()
            self.status_text.set('Programación de ANPR y Personas guardada; el servicio permanece activo')
        ttk.Button(automatic, text='Guardar envío automático', command=lambda: self.guarded(persist)).pack(anchor='w', pady=5)

    def anpr_result(self, rows):
        self.refresh_anpr(schedule=False)
        pending = [row for row in rows if row['state'] != 'delivered']
        if pending:
            messagebox.showwarning('Revise la cola ANPR', '\n'.join(row['message'] or 'Pendiente de enviar' for row in pending[:6]))
        else:
            messagebox.showinfo('ANPR recibido', 'Los archivos tienen comprobante de recepción. Revise el resultado en Comprobaciones.')

    def refresh_anpr(self, schedule=True):
        selection = self.anpr_table.selection()
        self.anpr_table.delete(*self.anpr_table.get_children())
        labels = {'pending':'Pendiente', 'sending':'Enviando', 'delivered':'Recibido', 'blocked':'Revisar', 'uncertain':'Verificar recepción'}
        for row in self.outbox.list():
            self.anpr_table.insert('', 'end', iid=row['batch_id'], values=(row['filename'], labels.get(row['state'], row['state']), row['receipt_id'] or ''))
        if selection and self.anpr_table.exists(selection[0]):
            self.anpr_table.selection_set(selection[0])
        elif self.outbox.export_jobs():
            job = self.outbox.export_jobs()[0]
            self.anpr_detail.config(text='Exportación ' + job['day'] + ': ' + job['message'])
        if schedule:
            self.root.after(5000, self.refresh_anpr)

    def cameras(self, frame):
        ttk.Label(frame, text='Pegue la lista completa una sola vez. Al probar, se detectan ID, modelo, firmware y canal de conteo.').pack(anchor='w', pady=(0, 10))
        self.table = ttk.Treeview(frame, columns=('name', 'host', 'location', 'model', 'status'), show='headings', height=11)
        for key, title, width in zip(self.table['columns'], ('Cámara', 'Dirección', 'Nivel', 'Modelo', 'Estado'), (235, 140, 90, 220, 160)):
            self.table.heading(key, text=title)
            self.table.column(key, width=width, minwidth=65)
        self.table.pack(fill='both', expand=True)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x', pady=10)
        ttk.Button(buttons, text='Importar cámaras', command=self.import_dialog).pack(side='left')
        ttk.Button(buttons, text='Probar cámaras', command=self.test_cameras).pack(side='left', padx=8)
        self.action_menu(buttons, [
            ('Agregar o editar seleccionada', self.edit_camera),
            ('Quitar seleccionada', self.remove_camera),
            (None, None),
            ('Exportar diagnóstico', self.export_diagnostics),
        ], text='Administrar').pack(side='left')
        credentials = ttk.LabelFrame(frame, text='Credenciales compartidas de cámaras', padding=10)
        credentials.pack(fill='x')
        user = self.field(credentials, 'Usuario', secret=True)
        password = self.field(credentials, 'Contraseña', secret=True)
        def persist():
            if not user.get() or not password.get():
                raise ValueError('Ingrese usuario y contraseña.')
            value = {'username': user.get(), 'password': password.get()}
            store_secret('camera-default', value)
            for camera in self.config.get('cameras', []):
                store_secret('camera/' + camera['external_id'], value)
            user.set('')
            password.set('')
            self.status_text.set('Credenciales guardadas para las cámaras configuradas')
        ttk.Button(credentials, text='Guardar para todas', command=lambda: self.guarded(persist)).pack(anchor='w', pady=8)

    def import_dialog(self):
        if self.busy:
            return
        win = tk.Toplevel(self.root)
        win.title('Importar cámaras')
        win.geometry('820x440')
        win.grab_set()
        ttk.Label(win, text='Pegue desde Excel: Nombre, Nivel, Grupo e IP. También admite punto y coma.').pack(anchor='w', padx=12, pady=12)
        text = tk.Text(win, height=12, wrap='none')
        text.pack(fill='both', expand=True, padx=12)
        def persist():
            items = parse_inventory(text.get('1.0', 'end'))
            for camera in items:
                existing = next((c for c in self.config['cameras'] if c['ip'] == camera['ip']), None)
                if existing:
                    existing.update({k: camera[k] for k in ('name', 'location', 'group')})
                else:
                    self.config['cameras'].append(camera)
            save(self.config)
            self.refresh()
            win.destroy()
            self.status_text.set('Lista importada. Use Probar cámaras para detectar sus datos.')
        ttk.Button(win, text='Importar lista', command=lambda: self.guarded(persist)).pack(pady=12)

    def edit_camera(self):
        if self.busy:
            return
        selection = self.table.selection()
        index = int(selection[0]) if selection else None
        cam = dict(self.config['cameras'][index]) if index is not None else {}
        win = tk.Toplevel(self.root)
        win.title('Cámara')
        win.geometry('560x560')
        win.grab_set()
        body = ttk.Frame(win, padding=12)
        body.pack(fill='both', expand=True)
        fields = {key: self.field(body, label, cam.get(key, '')) for key, label in [('name', 'Nombre'), ('ip', 'IP o nombre de red'), ('location', 'Nivel / ubicación'), ('group', 'Grupo') ]}
        user = self.field(body, 'Usuario propio de esta cámara (opcional)', secret=True)
        password = self.field(body, 'Contraseña propia (opcional)', secret=True)
        def persist():
            value = {k: v.get().strip() for k, v in fields.items()}
            from relleno.cameras import host_url
            import hashlib
            host_url(value['ip'])
            if not value['name']:
                raise ValueError('Ingrese el nombre de la cámara.')
            if any(c['ip'] == value['ip'] for i, c in enumerate(self.config['cameras']) if i != index):
                raise ValueError('Esa dirección ya está en la lista.')
            if not cam or cam.get('ip') != value['ip']:
                value.update(external_id='pending-'+hashlib.sha256(value['ip'].encode()).hexdigest()[:16], source_kind='pending', direction='pending', connection_status='Sin probar')
            else:
                value = cam | value
            if user.get() or password.get():
                if not user.get() or not password.get():
                    raise ValueError('Ingrese usuario y contraseña juntos.')
                store_secret('camera/' + value['external_id'], {'username': user.get(), 'password': password.get()})
            if index is None:
                self.config['cameras'].append(value)
            else:
                self.config['cameras'][index] = value
            save(self.config)
            self.refresh()
            win.destroy()
        ttk.Button(body, text='Guardar', command=lambda: self.guarded(persist)).pack(pady=12)

    def remove_camera(self):
        if self.busy:
            return
        if self.table.selection():
            self.config['cameras'].pop(int(self.table.selection()[0]))
            save(self.config)
            self.refresh()

    def export_diagnostics(self):
        from relleno.diagnostics import export
        try:
            target = export()
        except Exception as exc:
            messagebox.showerror('Diagnóstico', f'No se pudo exportar: {exc}')
            return
        messagebox.showinfo('Diagnóstico', f'Se guardó en el escritorio:\n{target.name}\n\nNo contiene contraseñas.')

    def test_cameras(self):
        cameras = list(self.config['cameras'])
        def work():
            results = []
            for camera in cameras:
                try:
                    results.append(probe(camera))
                except CameraError as exc:
                    results.append(dict(camera, connection_status=str(exc)))
            return results
        def done(results):
            self.config['cameras'] = results
            people = self.config.setdefault('people', {})
            if 'auto_export_enabled' not in people and any(
                camera.get('counting_enabled') and camera.get('source_kind') == 'people_counter'
                for camera in results
            ):
                yesterday = (
                    datetime.now(ZoneInfo(self.config.get('timezone', 'America/Santiago')))
                    - timedelta(days=1)
                ).date()
                people.update(auto_export_enabled=True, export_since=str(yesterday))
            save(self.config)
            self.refresh()
        self.background('Probando cámaras e identificando modelo y canal de conteo…', work, done)

    def counts(self, frame):
        ttk.Label(frame, text='Consulta por cámara y día. Se conservan las respuestas originales y los ceros reales.').pack(anchor='w')
        yesterday = (datetime.now(ZoneInfo(self.config.get('timezone', 'America/Santiago'))) - timedelta(days=1)).date()
        range_row = ttk.Frame(frame)
        range_row.pack(fill='x', pady=10)
        ttk.Label(range_row, text='Desde').pack(side='left')
        first_day = tk.StringVar(value=str(yesterday))
        ttk.Entry(range_row, textvariable=first_day, width=12).pack(side='left', padx=(6, 10))
        ttk.Label(range_row, text='Hasta').pack(side='left')
        last_day = tk.StringVar(value=str(yesterday))
        ttk.Entry(range_row, textvariable=last_day, width=12).pack(side='left', padx=(6, 10))
        self.count_table = ttk.Treeview(frame, columns=('camera', 'start', 'end', 'entries', 'exits'), show='headings', height=16)
        for key, title, width in zip(self.count_table['columns'], ('Cámara', 'Desde', 'Hasta', 'Entradas', 'Salidas'), (220, 240, 240, 90, 90)):
            self.count_table.heading(key, text=title)
            self.count_table.column(key, width=width)
        self.count_table.pack(fill='both', expand=True, pady=12)
        def run():
            try:
                selected_days = completed_days(
                    first_day.get(), last_day.get(), self.config['timezone']
                )
            except ValueError as exc:
                messagebox.showerror('Rango inválido', str(exc))
                return
            cameras = list(self.config['cameras'])
            zone = self.config['timezone']
            centre_id = self.config.get('binding', {}).get('centre_id')
            def work():
                batches, errors, tested = [], [], []
                from relleno.people import send_batch
                for camera in cameras:
                    current = camera
                    try:
                        if not current.get('model') or current.get('source_kind') in {'', 'pending', None}:
                            current = probe(current)
                        for selected in selected_days:
                            try:
                                batch = extract_day(current, selected, zone, centre_id)
                                send_batch(self.config['binding'], batch)
                                batches.append(batch)
                            except (CameraError, ValueError) as exc:
                                errors.append(f"{selected} · {camera['name']}: {exc}")
                    except (CameraError, ValueError) as exc:
                        current = dict(current, connection_status=str(exc))
                        errors.append(camera['name'] + ': ' + str(exc))
                    tested.append(current)
                return batches, errors, tested
            def done(result):
                batches, errors, tested = result
                self.config['cameras'] = tested
                save(self.config)
                self.count_table.delete(*self.count_table.get_children())
                for batch in batches:
                    for row in batch['intervals']:
                        self.count_table.insert('', 'end', values=[batch['camera']['name'], row['start'], row['end'], row['entries'], row['exits']])
                if errors:
                    messagebox.showwarning('Consultas pendientes', '\n'.join(errors[:12]))
                else:
                    messagebox.showinfo('Personas recibidas', f'{len(batches)} envíos de cámara/día confirmados por Comprobaciones.')
            self.background(
                f'Consultando y enviando {len(selected_days)} día(s) por cámara…', work, done
            )
        ttk.Button(range_row, text='Consultar y enviar', command=run).pack(side='left')
        automatic = ttk.LabelFrame(frame, text='Extracción automática de Personas', padding=10)
        automatic.pack(fill='x', pady=10)
        people_settings = self.config.get('people', {})
        daily = tk.BooleanVar(value=people_settings.get('auto_export_enabled', False))
        ttk.Checkbutton(
            automatic,
            text='Consultar y enviar cada día terminado (a partir de la 01:00)',
            variable=daily,
        ).pack(anchor='w', pady=3)
        def persist_people_schedule():
            if daily.get() and not self.config.get('binding'):
                raise ValueError('Vincule el equipo antes de activar la extracción automática.')
            previous = self.config.get('people', {})
            first = previous.get('export_since', str(yesterday))
            self.config['people'] = previous | {
                'auto_export_enabled': daily.get(),
                'export_since': first,
            }
            save(self.config)
            from relleno.anpr_worker import autostart, start
            autostart(bool(self.config.get('binding')))
            if self.config.get('binding'):
                start()
            self.status_text.set('Programación de Personas guardada')
        ttk.Button(
            automatic,
            text='Guardar programación de Personas',
            command=lambda: self.guarded(persist_people_schedule),
        ).pack(anchor='w', pady=5)

    def hikcentral(self, frame):
        from relleno.hikcentral import normalize_url, check, read_certificate_fingerprint, is_local_url
        current = self.config.get('hikcentral', {})
        url = self.field(frame, 'Dirección web real del servidor HikCentral (URL con puerto)', current.get('url', ''))
        method = self.field(frame, 'Autenticación', current.get('method', 'username'), choices=('username', 'appkey'))
        account = self.field(frame, 'Usuario o AppKey', secret=True)
        secret = self.field(frame, 'Contraseña o SecretKey', secret=True)
        status = ttk.Label(frame, text=current.get('connection_status', 'Sin comprobar'), wraplength=950)
        status.pack(anchor='w', pady=10)
        ttk.Label(frame, text='Use la misma dirección que abre el portal web de HikCentral en el navegador; puede ser 127.0.0.1 cuando el Web Client está instalado en este PC.\nCredenciales guardadas en Windows. Los campos vacíos conservan las existentes.', wraplength=950).pack(anchor='w', pady=12)
        def persist_and_test():
            value = normalize_url(url.get())
            if account.get() or secret.get():
                if not account.get() or not secret.get():
                    raise ValueError('Ingrese ambas partes de la credencial.')
                store_secret('hikcentral', {'method': method.get(), 'account': account.get(), 'secret': secret.get()})
            previous = self.config.get('hikcentral', {})
            settings = previous | {'url': value, 'method': method.get()}
            if previous.get('url') != value:
                settings.pop('certificate_sha256', None)
            settings['connection_status'] = 'Comprobando conexión…'
            self.config['hikcentral'] = settings
            save(self.config)
            status.config(text=settings['connection_status'])
            account.set('')
            secret.set('')
            def work():
                if value.startswith('https://') and is_local_url(value):
                    settings['certificate_sha256'] = read_certificate_fingerprint(value)
                    self.config['hikcentral'] = settings
                    save(self.config)
                return check(settings)
            def done(message):
                settings['connection_status'] = message
                self.config['hikcentral'] = settings
                save(self.config)
                status.config(text=message)
            self.background('Guardando y comprobando HikCentral…', work, done)
        ttk.Button(
            frame, text='Guardar y comprobar', command=lambda: self.guarded(persist_and_test)
        ).pack(anchor='w', pady=8)
        ttk.Label(frame, text='Las siete cámaras de conteo se consultan directamente; no requieren AppKey de HikCentral.\nPara ANPR se conservarán los XLS/XLSX/XLSM originales; no se generarán a partir de los conteos.', wraplength=950).pack(anchor='w', pady=12)


def main():
    root = tk.Tk()
    try:
        App(root)
    except Exception:
        messagebox.showerror('No se pudo abrir', 'Revise los permisos de la configuración local y del Administrador de credenciales de Windows.')
        root.destroy()
        return
    root.mainloop()
