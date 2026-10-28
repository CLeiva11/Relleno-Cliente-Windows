# Instalación y prueba en Gran Avenida

## Preparación

1. Descargue `RellenoCliente-Setup-0.4.27.exe` y `SHA256SUMS.txt` desde la última versión publicada en GitHub Releases.
2. Ejecute el instalador con el mismo usuario de Windows que usa HikCentral. Puede instalarse sobre la versión anterior: conserva vínculo, cámaras, certificados y credenciales guardadas.
3. Abra **Relleno Cliente** y confirme que el centro vinculado sea **Espacio Urbano Gran Avenida**.
4. En **HikCentral**, configure la URL local, usuario y contraseña. Pulse **Guardar y comprobar**.
5. Mantenga desactivado el envío automático durante esta primera prueba.

## Diagnóstico remoto

1. Deje iniciada la sesión de Windows. El navegador de automatización necesita una sesión interactiva disponible.
2. En SIEM abra **Relleno > Comprobaciones > Espacio Urbano Gran Avenida**.
3. Verifique que el equipo figure **activo**, con versión `0.4.27` y capacidad de Vehículos.
4. Seleccione un día terminado que tenga conteos ANPR conocidos.
5. Pulse **Diagnosticar HikCentral** y confirme una sola vez.
6. Espere a que el estado cambie de **En espera** a **Procesando** y luego a **Completado** o **Falló**.
7. Pulse **Descargar diagnóstico**. El ZIP contiene `summary.json`, `steps.json` y capturas por etapa. Los campos de entrada y resultados sensibles se ocultan; no incluye el Excel ANPR.

## Prueba de datos

1. Cuando el diagnóstico complete el recorrido correcto, solicite **Generar ANPR** para el mismo día.
2. Abra la recepción en el calendario y revise cámara por cámara.
3. No pulse **Corregir diferencias** durante la validación inicial. Primero confirme que fecha, cámaras, direcciones y deduplicación correspondan a Gran Avenida.
4. Active el envío automático solo después de validar al menos un día completo.

Si falla, entregue únicamente el ZIP descargado desde Comprobaciones. No es necesario abrir GitHub, ChatGPT ni acceso SSH en el equipo del centro.
