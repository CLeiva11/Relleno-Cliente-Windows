# Relleno Cliente Windows

Cliente Windows para obtener datos Hikvision y enviarlos al módulo
**Comprobaciones** del portal de Relleno.

El portal maneja únicamente:

- **Personas:** conteos obtenidos desde el portal web de cámaras de conteo o cámaras
  RF.
- **Vehículos:** registros ANPR exportados desde HikCentral.

Este repositorio no debe contener Django, scripts de relleno, conexiones MySQL ni
credenciales. La comparación y la corrección se ejecutan en el portal.

El agente que continúe el desarrollo debe leer primero [AGENTS.md](AGENTS.md).

## Instalador 0.3.0

[Descargar el instalador para Windows desde Releases](https://github.com/CLeiva11/Relleno-Cliente-Windows/releases/latest).
El archivo es `RellenoCliente-Setup-0.3.0.exe`. Incluye exportación ANPR diaria
desde HikCentral y envío autenticado a Comprobaciones, carga de Excel originales,
cola persistente y arranque con Windows. No necesita Python ni herramientas de
desarrollo después de instalar. Usa Microsoft Edge instalado en Windows.
Consulte [ESTADO.md](ESTADO.md) para uso, compilación y limitaciones.

El mismo instalador se puede copiar e instalar en otros equipos y centros.
Cada equipo se vincula con su propio código de Comprobaciones y configura su
HikCentral. El instalador no incluye el vínculo, inventario, credenciales ni
archivos del centro piloto. Consulte [INSTALACION.md](INSTALACION.md).

`dist/` permanece excluido de Git: el código fuente se versiona en el repositorio
y el instalador se publica como archivo adjunto de una versión en **Releases**.

La exportación web ANPR y su recepción real en el portal se validaron en el piloto.
La lectura de Personas también funciona, pero su envío continúa deshabilitado
porque el portal no devuelve su endpoint.

## Estado de integración

- El portal ya permite vincular un equipo mediante código de un solo uso.
- El endpoint autenticado para archivos ANPR ya está definido.
- El endpoint para conteos de Personas debe habilitarse en el portal y devolverse
  durante la vinculación.
- ANPR usa la exportación Excel nativa del portal web de HikCentral con las
  credenciales locales guardadas; no necesita AppKey para este método.
