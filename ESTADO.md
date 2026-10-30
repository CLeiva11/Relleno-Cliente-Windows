# Entrega 0.4.34

Las actualizaciones silenciosas vuelven a abrir la ventana al terminar y reinician
el agente en segundo plano sin dejar al instalador esperando su cierre.

HikCentral queda administrado automáticamente: no muestra campos de URL, usuario ni
contraseña. Usa el Web Client local, actualiza su huella de certificado y prueba en
orden las claves incluidas fuera de Git durante la compilación. Solo reintenta con la
segunda clave cuando HikCentral rechaza la autenticación.

Inicio incorpora **Buscar actualización** junto al estado del portal. Informa la
versión instalada, consulta el canal autenticado y, previa confirmación, descarga,
verifica e instala de inmediato la versión disponible.

La navegación ANPR espera ahora que desaparezca la carga inicial de HikCentral
y reintenta tres veces la pestaña antes de recurrir a una ruta alternativa. Esto
evita que un clic descartado por el panel de inicio intermitente impida exportar.

La navegación ANPR ahora prioriza la pestaña exacta `ANPR` cuando HikCentral
también muestra `Vehículo` antes en la barra principal. Además cierra el aviso
inicial de la tienda de aplicaciones por su botón antes de buscar los controles.
Este ajuste corresponde al diagnóstico de La Laguna del 29 de octubre.

Por autorización del operador, Personas envía ceros estimados cuando una cámara
no responde por HTTP/HTTPS. Conserva el inventario, cámara, dirección y zona
horaria; genera intervalos horarios también en días de 23 o 25 horas. Si HTTPS
con huella guardada no responde, intenta HTTP una sola vez. Los cambios de
certificado, autenticación rechazada, respuestas HTTP de error y conteos
incompletos continúan fallando sin generar ceros.

El JSON incluye `quality.estimated`, `reason: camera_unreachable` y
`requires_manual_review`; la evidencia local conserva el motivo sin credenciales.
El lote usa un ID determinista separado del conteo real y se muestra como
`0 estimado` en Conteos. Al recuperar conectividad se consulta la fuente de nuevo;
no se reutiliza un estimado como dato medido. La regla se aplica a consultas
manuales, programadas y órdenes remotas. El portal debe conservar y mostrar los
metadatos de calidad para distinguirlos en su interfaz; el cliente no puede
asegurar ese comportamiento del servidor. La corrección sigue siendo manual.
No se enviaron ceros a cámaras reales durante las pruebas de esta entrega.
92 pruebas automatizadas aprobadas.


ANPR conserva siempre el Excel original descargado desde HikCentral, tanto en
la interfaz nueva como en la anterior. Se elimina la ruta que reconstruía un
Excel desde los registros API: sus valores numéricos de dirección provocaban que
el portal descartara todas las filas. Las exportaciones generadas anteriormente
se conservan con su manifiesto y recepción; una nueva solicitud del mismo día
obtiene y reutiliza un Excel nativo separado. Si el portal confirma recepción
pero falla el procesamiento, la cola muestra un aviso sin reenviar a ciegas.

Validación del 22 de octubre: archivo original de 7.573 filas; el portal reconoce
6.172 registros de 9 cámaras, sin cámaras sin mapear, y descarta 1.401 por su filtro
de dirección. No se alteran las filas ni se ejecutan correcciones de base de datos.
Las pruebas automatizadas pasan.

La extracción detecta capacidades ISAPI y prueba cuerpos estadísticos conocidos
de firmware nuevo y legado. HikCentral reconoce las variantes de interfaz en
español e inglés; una versión desconocida se detiene y genera diagnóstico, sin
crear conteos en cero ni exportar otro intervalo.
La versión 0.4.21 reconoce cuando HikCentral confirma el rango al cerrar su
calendario automáticamente y continúa la consulta sin esperar un botón inexistente.
La versión 0.4.23 espera que termine de cargar el árbol ANPR, cierra avisos tardíos
de la tienda de aplicaciones y verifica la selección completa antes de consultar.
ANPR y Conteos permiten enviar un rango inclusivo de hasta 31 días terminados;
cada cámara y fecha conserva su recepción independiente en Comprobaciones.

Ejecute `dist/RellenoCliente-Setup-0.4.34.exe` en Windows x64 con su usuario habitual.
El instalador conserva el perfil local y el vínculo existente.

Comprobaciones puede solicitar un diagnóstico remoto de HikCentral. Este recorre
la interfaz real, no envía ANPR ni corrige datos y devuelve evidencia redactada al portal.
El actualizador consulta el canal autenticado del portal cada seis horas. Solo
ejecuta instaladores con versión superior, tamaño exacto, cabecera PE y SHA-256 válido.
No necesita Python. Abra Relleno Cliente desde Inicio o el escritorio.

En Inicio, confirme el vínculo administrativo y configure la zona horaria. El
centro queda fijado por el portal. Si ya está vinculado, se muestra directamente
el centro y se oculta el formulario.
En Cámaras, importe cuatro columnas (Nombre, Nivel, Grupo, IP), guarde credenciales
compartidas y pulse Probar cámaras. Se detectan ID estable, modelo, firmware y región.
Puede agregar/editar o quitar cámaras; cada una admite credenciales propias.
Nivel y grupo se conservan separados de la región de conteo detectada.
HikCentral no es configurable desde la aplicación. El cliente usa exclusivamente
el Web Client local y fija automáticamente su certificado antes de exportar ANPR.
Esto no desactiva TLS del portal de Relleno.

Los tokens y secretos de cámaras se guardan en Windows Credential Manager con prefijo
`RellenoCliente/`. Las claves administradas de HikCentral se inyectan al compilar y
nunca se escriben en `config.json` ni se guardan en Git.

En Conteos seleccione un día terminado y consulte todas las cámaras. El adaptador
de DS-2CD6825 se basa en la consulta ISAPI usada por el portal web y se validó con
las siete cámaras del equipo piloto (firmware V5.8.10). Lee Entradas y Salidas por
hora, sin inferirlas del nombre de acceso/salida, sin sumar cámaras ni regiones y
sin convertir datos incompletos en cero; la falta de conexión usa el estimado autorizado. Rechaza horas ambiguas por horario de verano.
Solo admite una región por cámara en este adaptador. RF continúa siendo Personas,
pero necesita validar su modelo antes de extraer.

Las respuestas XML y lotes JSON se conservan en la carpeta local `batches`, con ID
determinista por centro, cámara, fuente, región, dirección, día y zona horaria.
Una cerradura del sistema evita consultas simultáneas de la misma ventana y se
libera tras un reinicio. Consultas repetidas reutilizan el lote local conservado.

## ANPR: exportación y envío

En la pestaña ANPR puede elegir una fecha terminada y usar **Exportar de HikCentral
y enviar**. El cliente inicia sesión en su portal web, selecciona las cámaras ANPR
y fija el día completo. Se conserva la respuesta de conteo y se descarga el
Excel nativo sin imágenes. No se reconstruyen tablas desde la API ni se traducen
valores de dirección, encabezados o nombres de cámaras.
Se utiliza Microsoft Edge en segundo plano y no requiere AppKey/SecretKey.

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

Los adaptadores de red están separados por familia para incorporar otras versiones
sin mezclar sus contratos. Los cambios de interfaz o API pueden requerir uno nuevo.
No se generan archivos ANPR parciales ni ceros por errores de formato. La falta
de conectividad en Personas usa el cero estimado autorizado descrito arriba. Un
fallo de autenticación no provoca intentos indefinidos.

El servicio envía un pulso cada minuto y consulta órdenes del portal cada 15
segundos. Desde Comprobaciones se puede solicitar Personas o ANPR para un día
terminado; la extracción utiliza los mismos adaptadores, copias locales y colas
que la ejecución manual y programada. Recibir datos no ejecuta una corrección:
ésta se confirma por separado en Comprobaciones.

Personas se envía cámara por cámara al endpoint autenticado y conserva Entradas,
Salidas e intervalos horarios. La detección se hace por capacidad ISAPI y contempla
DS-2CD6825G0/C-IVS e iDS-2CD7146G0-IZS, incluso cuando el segundo expone una regla
global sin `CountingRegionList`. La programación diaria se ejecuta desde la 01:00,
conserva pendientes tras reinicios y distingue los ceros estimados autorizados de los conteos reales. La
casilla general programa ANPR y Personas cuando ambos canales están configurados.
La región del centro no forma parte del lote: el portal la resuelve desde `camaras`
después de identificar el dispositivo por ID/IP.

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
