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

## Estado inicial

- El portal ya permite vincular un equipo mediante código de un solo uso.
- El endpoint autenticado para archivos ANPR ya está definido.
- El endpoint para conteos de Personas todavía debe implementarse en el portal.
- La extracción desde cámaras y HikCentral debe desarrollarse y validarse en un
  centro piloto antes de crear el instalador definitivo.
