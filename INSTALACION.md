# Instalación en un centro

1. Descargue `RellenoCliente-Setup-0.4.32.exe` desde
   [Releases](https://github.com/CLeiva11/Relleno-Cliente-Windows/releases/latest).
   También puede copiar ese mismo archivo por USB o por el canal de distribución
   del equipo. Si el repositorio es privado, GitHub exige acceso para descargarlo.
2. Ejecute el instalador en Windows x64, con el usuario que operará el cliente.
   No necesita instalar Python. Debe tener Microsoft Edge instalado.
3. En una actualización, el vínculo existente se conserva. Para una instalación
   nueva, el vínculo debe ser provisionado por administración; el portal operativo
   no expone generación de códigos a usuarios.
4. En HikCentral indique la dirección del servidor, usuario y contraseña con permisos
   para buscar y exportar ANPR. `localhost` se refiere al equipo donde instala el
   cliente; solo sirve si HikCentral está en ese mismo equipo.
5. En ANPR elija un día terminado y pulse **Exportar de HikCentral y enviar**.
   Compruebe que aparece **Recibido** y un comprobante del portal.
6. Active la exportación diaria y guarde la configuración. Se procesan los días
   terminados desde la activación, a partir de la 01:00 en la zona horaria configurada.
   El equipo debe estar encendido y un usuario con sesión iniciada. El cliente
   arranca con Windows y puede seguir trabajando con su ventana cerrada.
7. Compruebe en Inicio que el portal confirma la señal. Desde Comprobaciones podrá
   solicitar Personas o ANPR para un día terminado sin afectar la programación.
8. Desde esta versión, las siguientes actualizaciones aprobadas se descargarán e
   instalarán automáticamente desde el portal, sin abrir GitHub en el equipo.
9. En Conteos, active la extracción diaria de Personas si el centro utiliza cámaras
   DS-2CD6825G0/C-IVS o iDS-2CD7146G0-IZS y confirme que Probar cámaras detecta el
   conteo habilitado.

Para recuperar varios días, indique Desde y Hasta en ANPR o Conteos. El rango
manual admite hasta 31 días terminados y envía cada fecha por separado.

El instalador es reutilizable; la configuración es propia de cada equipo. No
copie `config.json`, la cola ni las credenciales del centro piloto a otro centro.
El portal fija el centro por el vínculo: el cliente no ofrece elegir otra base.

Reinstalar o actualizar en el mismo usuario de Windows conserva el vínculo y los
datos locales. Desinstalar no convierte ese equipo en un equipo de otro centro.
Actualmente no hay un cambio de centro desde la interfaz; un traslado físico de
un equipo ya vinculado requiere gestionar el vínculo anterior y preparar un perfil
limpio antes de usar el código del nuevo centro.

Las credenciales y el token se guardan en Windows Credential Manager. Configuración,
fuentes y cola permanecen en `%LOCALAPPDATA%/RellenoCliente`, fuera del repositorio
y del instalador. Los certificados privados o autofirmados de direcciones locales
se detectan al probar la configuración y quedan fijados por su huella SHA-256.
La confianza se invalida al cambiar la dirección configurada.

La exportación web se validó en el piloto; otra versión o idioma de HikCentral
puede requerir ajustar el adaptador. No se necesitan AppKey/SecretKey para este
método. Los Excel originales también se pueden seleccionar y enviar directamente.

El instalador todavía no tiene firma de código. Compare su SHA-256 con
`SHA256SUMS.txt` de la misma versión si necesita comprobar la descarga.
La recepción no corrige la base: la corrección se confirma en Comprobaciones.
