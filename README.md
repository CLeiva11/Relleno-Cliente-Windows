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

## Versión 0.4.32

[Descargar el instalador para Windows desde Releases](https://github.com/CLeiva11/Relleno-Cliente-Windows/releases/latest).
El instalador es `RellenoCliente-Setup-0.4.32.exe`. Consulte
[ESTADO.md](ESTADO.md) para el estado de los artefactos de esta entrega. Incluye extracción ANPR diaria
desde HikCentral y envío autenticado a Comprobaciones, carga de Excel originales,
cola persistente y arranque con Windows. No necesita Python ni herramientas de
desarrollo después de instalar. Usa Microsoft Edge instalado en Windows.
La extracción manual de ANPR y Personas admite rangos de hasta 31 días terminados.
Consulte [ESTADO.md](ESTADO.md) para uso, compilación y limitaciones.

El mismo instalador se puede copiar e instalar en otros equipos y centros.
Cada equipo se vincula con su propio código de Comprobaciones y configura su
HikCentral. El instalador no incluye el vínculo, inventario, credenciales ni
archivos del centro piloto. Consulte [INSTALACION.md](INSTALACION.md).

`dist/` permanece excluido de Git: el código fuente se versiona en el repositorio
y el instalador se publica como archivo adjunto de una versión en **Releases**.

La exportación web ANPR y su recepción real en el portal se validaron en el piloto.
La lectura y el envío cámara por cámara de Personas están habilitados para equipos
que expongan el contrato ISAPI validado, incluidos DS-2CD6825G0/C-IVS e
iDS-2CD7146G0-IZS. El servicio
reporta su conexión al portal y acepta órdenes de generación de Personas o ANPR,
o un diagnóstico remoto de HikCentral que no envía ni corrige datos,
además de conservar la programación ANPR existente y permitir programar Personas.
Desde `0.4.29`, el servicio consulta cada seis horas una actualización aprobada
por el portal, verifica su SHA-256 y la instala silenciosamente.
La opción general de envío diario activa ambos canales disponibles. El cliente
identifica cada cámara por ID/IP; la región comercial se obtiene de la tabla
`camaras` en el portal y no se envía desde Windows.

## Estado de integración

- El portal ya permite vincular un equipo mediante código de un solo uso.
- El endpoint autenticado para archivos ANPR ya está definido.
- El endpoint para conteos de Personas está habilitado y se devuelve durante la
  vinculación junto con los endpoints de pulso y órdenes remotas.
- ANPR detecta adaptadores por familia de endpoints autenticados. La familia
  `Bumblebee/VehicleBiz/V0` pagina `VehicleLogs` y verifica sus filas contra
  `VehicleLogsCount`; otras versiones conservan la exportación web como respaldo.
  No necesita AppKey para estos métodos.
