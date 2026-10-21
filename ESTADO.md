# Entrega 0.3.0

Ejecute `dist/RellenoCliente-Setup-0.3.0.exe` en Windows x64 con su usuario habitual.
No necesita Python. Abra Relleno Cliente desde Inicio o el escritorio.

En Inicio, vincule mediante código nuevo de Comprobaciones y configure la zona
horaria. El centro queda fijado por el portal. Si ya está vinculado, se muestra
directamente el centro y se oculta el formulario.
En Cámaras, importe cuatro columnas (Nombre, Nivel, Grupo, IP), guarde credenciales
compartidas y pulse Probar todas. Se detectan ID estable, modelo, firmware y región.
Puede agregar/editar o quitar cámaras; cada una admite credenciales propias.
Nivel y grupo se conservan separados de la región de conteo detectada.
En HikCentral, configure dirección y autenticación y pruebe el acceso web.
Las direcciones sin protocolo se completan con HTTPS. La prueba web no autentica
al usuario. La exportación se valida desde ANPR. Para el servidor local del piloto se
registró una huella de certificado; no se desactiva TLS del portal de Relleno.

Los secretos se guardan exclusivamente en Windows Credential Manager con prefijo
`RellenoCliente/`. Cargue AppKey/SecretKey allí si la API disponible las requiere;
no las envíe por chat ni a Git. Dejar campos secretos vacíos conserva credenciales.
La configuración sin secretos está en `%LOCALAPPDATA%/RellenoCliente/config.json`.

En Conteos seleccione un día terminado y consulte todas las cámaras. El adaptador
de DS-2CD6825 se basa en la consulta ISAPI usada por el portal web y se validó con
las siete cámaras del equipo piloto (firmware V5.8.10). Lee Entradas y Salidas por
hora, sin inferirlas del nombre de acceso/salida, sin sumar cámaras ni regiones y
sin convertir datos ausentes en cero. Rechaza horas ambiguas por horario de verano.
Solo admite una región por cámara en este adaptador. RF continúa siendo Personas,
pero necesita validar su modelo antes de extraer.

Las respuestas XML y lotes JSON se conservan en la carpeta local `batches`, con ID
determinista por centro, cámara, fuente, región, dirección, día y zona horaria.
Una cerradura del sistema evita consultas simultáneas de la misma ventana y se
libera tras un reinicio. Consultas repetidas reutilizan el lote local conservado.

## ANPR: exportación y envío

En la pestaña ANPR puede elegir una fecha terminada y usar **Exportar de HikCentral
y enviar**. El cliente inicia sesión en su portal web, selecciona las cámaras
ANPR, fija el día completo y descarga el Excel nativo sin imágenes. Confirma la
contraseña de exportación con la credencial de Windows. Se utiliza Microsoft Edge
en segundo plano, sin descargar otro navegador. No requiere AppKey/SecretKey.
Se comprobaron la exportación web y su recepción real para tres cámaras del piloto.

Active la exportación diaria para procesar los días terminados a partir de la
01:00 en la zona horaria del centro. El monitor arranca al iniciar sesión en
Windows y sigue funcionando con la ventana cerrada. Debe haber un usuario con
sesión iniciada y acceso a HikCentral e Internet. Después de reinicios conserva
las ventanas pendientes desde la fecha de activación; no importa todo el historial.

También admite seleccionar uno o varios XLS/XLSX/XLSM originales, con encabezados
en español o inglés, sin traducirlos ni reescribirlos. El monitor de carpeta es
opcional y solo incorpora nuevos Excel cuyo nombre contenga ANPR, una vez estables.
Está separado de la exportación diaria y puede permanecer desactivado.

La cola SQLite y las copias originales están en `anpr` dentro del perfil local.
Calcula SHA-256, conserva los bytes originales y el nombre de archivo y envía
`source_files` con Bearer exclusivamente al `upload_url` del vínculo. Un archivo
idéntico del mismo centro no vuelve a enviarse desde la cola, aunque cambie de
nombre. Cada exportación diaria conserva su manifiesto y se reutiliza al repetir
la ventana para evitar generar otra copia con metadatos Excel distintos.

El ID de recepción se guarda junto con el estado entregado en una transacción.
Se conservan fuente y respuesta después de recibir para facilitar la revisión.
Un bloqueo de Windows impide envíos/extracciones simultáneos. Los logs rotan sin
contraseñas, tokens, cuerpos HTTP ni trazas de automatización.

Los fallos de conexión antes de enviar usan backoff. Los errores 4xx se bloquean.
Si la conexión se interrumpe después de un posible envío, o hay un 5xx, no se
repite a ciegas: queda **Verificar recepción** hasta revisar Comprobaciones. El
contrato disponible del servidor no garantiza idempotencia remota ante un timeout.
Se envía un Idempotency-Key estable; reintentar automáticamente respuestas ambiguas
requiere que el portal confirme esa garantía. No se afirma entrega sin ID.

Los cambios de interfaz web de HikCentral pueden requerir actualizar el adaptador.
No se generan conteos cero ante un fallo de consulta ni se fabrican Excel a partir
de JSON. Un fallo de autenticación no provoca intentos indefinidos.

El portal no devolvió `people_count_url`, por lo que Personas sigue deshabilitado
para envío. El cliente no compara ni corrige bases de datos. Recibir ANPR no
ejecuta una corrección: se confirma en Comprobaciones.

La API oficial es una alternativa que requiere AppKey/SecretKey y permisos propios;
la exportación web validada utiliza el usuario y contraseña ya disponibles.
Los datos reales del piloto están exclusivamente en el perfil local de Windows;
no se incluyen en el instalador ni en Git. Reinstalar en este equipo conserva la
configuración; instalar en otro equipo requiere su propio inventario y vínculo.

El instalador no tiene firma de código: falta certificado del distribuidor.
La desinstalación conserva configuración y credenciales para reinstalar.
Puede eliminarlas desde la carpeta indicada y el Administrador de credenciales.

## Compilación

Python 3.11+ y `requirements.txt`; Inno Setup 6 en `.tools/inno` o su carpeta
predeterminada de Program Files (x86). Ejecute `build.ps1`.
En esta entrega `tzdata` se instaló en `.build-deps`; también puede instalarse en
el entorno Python. Playwright está en `.automation-deps` o puede instalarse en el
entorno. Se incluye su controlador en el ejecutable y se usa Edge del sistema.
Las carpetas de compilación están excluidas de Git.

Pruebas: `python -m unittest discover -s tests -v`.
El ejecutable acepta `--self-test` para probar interfaz y zona horaria sin mostrar
ventana ni conectar al portal.
