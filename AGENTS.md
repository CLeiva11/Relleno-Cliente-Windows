# Instrucciones para el agente de desarrollo

## Objetivo

Construir un cliente Windows instalable que extraiga datos Hikvision y los entregue
al módulo **Comprobaciones** del portal de Relleno. El operador no debe necesitar
abrir herramientas de desarrollo después de instalarlo.

El vínculo fija el centro y entrega un token; el usuario no elige bases de datos.
La interfaz operativa no genera códigos nuevos: el alta se provisiona por
administración y una actualización conserva el vínculo existente.

## Modelo del portal

El portal conoce solo dos tipos de datos:

| Dato | Fuente local |
| --- | --- |
| `personas` | Portal web de una cámara de conteo o de una cámara RF |
| `vehiculos` | Registros ANPR exportados desde HikCentral |

Una cámara RF es otra fuente de conteo de **Personas**. No crear una analítica RF
separada ni enviar sexo, edad o porcentajes. Desde cámaras de conteo y RF se obtienen
Entradas y Salidas por cámara e intervalo.

## Límites obligatorios

- El cliente extrae y envía; nunca compara ni corrige bases de datos.
- No agregar Django, scripts de relleno ni conexiones MySQL.
- No guardar IP privadas, usuarios, contraseñas, tokens o códigos reales en Git.
  HikCentral es una configuración administrada: el código fija loopback y el usuario,
  mientras las claves se inyectan en `_managed_hikcentral.py` durante el build y ese
  archivo permanece ignorado por Git.
- Guardar secretos con Windows Credential Manager, por ejemplo mediante `keyring`.
- Nunca enviar credenciales de cámaras o HikCentral al portal.
- Mantener datos separados por cámara, dirección e intervalo. La región comercial
  pertenece a la tabla `camaras` del portal y no se define en Windows.
- `0` es válido. Por autorización expresa del operador, la falta de conexión
  HTTP/HTTPS en cámaras de Personas produce ceros estimados por intervalo para
  comparación y revisión manual. Identificarlos con `quality.estimated: true`,
  `reason: camera_unreachable` y `requires_manual_review: true`, conservando
  evidencia local y un ID distinto del conteo real. No aplicar esta excepción
  a autenticación, certificados cambiados, errores HTTP o datos incompletos.
- Conservar archivos y respuestas fuente hasta que el servidor confirme recepción.
- La plataforma decide el mapeo, comparación, reglas especiales y corrección.

## Vinculación

URL base de producción:

```text
https://siem.domoticatechnology.cl/relleno
```

Solicitud:

```text
POST /api/comprobaciones/agentes/vincular/
Content-Type: application/json
```

```json
{
  "code": "CODIGO_DE_UN_SOLO_USO",
  "agent_name": "EQUIPO-CENTRO-01"
}
```

Respuesta relevante del alta administrativa:

```json
{
  "ok": true,
  "agent_id": "...",
  "agent_token": "...",
  "centre_id": "...",
  "centre_name": "...",
  "upload_url": "/api/comprobaciones/agentes/anpr/",
  "people_count_url": "/api/comprobaciones/agentes/personas/",
  "heartbeat_url": "/api/comprobaciones/agentes/pulso/",
  "commands_url": "/api/comprobaciones/agentes/ordenes/",
  "command_result_url": "/api/comprobaciones/agentes/ordenes/resultado/"
}
```

El token se muestra una vez. Guardarlo en Windows Credential Manager. Exigir HTTPS,
salvo pruebas en `localhost`.

## Vehículos mediante ANPR

El endpoint disponible es la URL `upload_url` devuelta al vincular el agente:

```text
POST /api/comprobaciones/agentes/anpr/
Authorization: Bearer <agent_token>
Content-Type: multipart/form-data
```

Enviar uno o varios campos `source_files` con los XLS/XLSX/XLSM originales. Los
archivos pueden tener encabezados de HikCentral en español o inglés. No traducirlos,
no reescribirlos y no acumular las cámaras en el cliente.

La plataforma separa los registros por fecha y cámara, compara contra Vehículos y
solo corrige cuando el usuario lo confirma desde Comprobaciones.

## Personas desde cámaras

Hay dos orígenes posibles:

- `people_counter`: cámara dedicada de conteo.
- `rf_counter`: cámara RF usada como fuente de conteo.

En ambos casos se consulta el portal web de la cámara. Primero inspeccionar las
solicitudes HTTP/API utilizadas por ese portal; usar automatización visual solo si
no existe una consulta o exportación estable.

El portal implementa `people_count_url`. Los vínculos antiguos resuelven el endpoint
actual en el mismo host aunque no lo conserven en `config.json`. Nunca enviar
conteos al endpoint ANPR.

Contrato vigente para `people_count_url`:

```json
{
  "schema_version": 1,
  "data_type": "personas",
  "source_kind": "people_counter",
  "batch_id": "uuid-o-id-determinista",
  "timezone": "America/Santiago",
  "camera": {
    "external_id": "id-estable-hikvision",
    "name": "Nombre original",
    "ip": "IP local informativa",
    "direction": "bidirectional"
  },
  "intervals": [
    {
      "start": "2026-10-20T08:00:00-03:00",
      "end": "2026-10-20T09:00:00-03:00",
      "entries": 120,
      "exits": 83
    }
  ]
}
```

Para una cámara RF usar `source_kind: "rf_counter"`; el resto del contrato y el
destino Personas no cambian.

## Inventario requerido antes de programar extractores

Solicitar por centro:

- Nombre y código del centro en SIEM.
- Zona horaria y periodicidad requerida.
- ID, nombre, IP y dirección de cada cámara.
- Tipo por cámara: `people_counter`, `rf_counter` o `anpr`.
- Modelo y firmware de cada cámara de Personas.
- Forma actual de consultar el conteo en su portal web.
- Versión de HikCentral para ANPR. La URL y la cuenta no son configurables.
- Permisos disponibles para la cuenta administrada.
- Un archivo ANPR real en español y otro en inglés cuando corresponda.

Las claves administradas de HikCentral se entregan fuera de Git al proceso de build.
Las credenciales de cámaras se cargan directamente en el almacén seguro.

## Arquitectura esperada

Separar al menos estos componentes:

1. Configuración local sin secretos.
2. Inventario de cámaras.
3. Almacén seguro de credenciales.
4. Extractores por modelo o fuente.
5. Cola local idempotente.
6. Cliente HTTPS del portal.
7. Programador de ventanas pendientes.
8. Logs rotativos sin secretos.

Usar una interfaz común para extractores, pero no forzar el mismo formato de origen:
Personas produce lotes JSON cámara por cámara y Vehículos conserva archivos ANPR.

## Entrega y reintentos

- Crear un identificador determinista por centro, cámara, fuente y ventana.
- Para archivos ANPR calcular además SHA-256.
- No iniciar dos extracciones simultáneas de la misma ventana.
- Reintentar fallos de red y respuestas `5xx` con backoff.
- No reintentar indefinidamente errores `4xx` de formato o autenticación.
- Guardar el ID de recepción antes de marcar un lote como entregado.
- Recuperar la cola después de reinicios sin duplicar recepciones.

## Servicio y órdenes remotas

- El trabajador arranca con Windows cuando el equipo está vinculado.
- Envía pulso cada minuto y consulta órdenes cada 15 segundos.
- Una orden reutiliza el extractor de Personas o la exportación/cola ANPR existente.
- La programación ANPR continúa activa de forma independiente.
- El resultado vuelve al portal con los IDs de recepción; una falla queda visible y
  puede solicitarse nuevamente sin cambiar de centro.

## Criterios de aceptación

- Una actualización conserva el vínculo y reactiva el servicio en el inicio de Windows.
- El token y las credenciales nunca quedan en archivos de texto o logs.
- Cada cámara se identifica de manera estable por ID/IP; el portal obtiene su
  región desde la base y conserva la dirección del conteo.
- Personas diferencia cero real, cero estimado por falta de conexión y dato ausente.
- ANPR conserva el archivo original y admite español e inglés.
- La pérdida de red o un reinicio no pierde ni duplica lotes.
- El portal recibe datos del centro vinculado y no permite elegir otro centro.
- Ninguna recepción modifica la base automáticamente; la corrección requiere
  confirmación del usuario.
