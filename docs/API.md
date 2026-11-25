# API

> Borrador del contrato. FastAPI genera la especificación OpenAPI completa en `/api/docs` cuando el backend exista; este documento fija los recursos y el streaming para que backend y frontend avancen en paralelo.

Convenciones: JSON, prefijo `/api`, identificadores UUID, errores con forma `{"error": {"code": "…", "message": "…", "details": {…}}}`. Autenticación con `Authorization: Bearer <jwt>` desde el hito M3; antes, modo desarrollo sin login.

## Salud

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/health` | Estado, versión y conectividad con la BD de la app |

## Fuentes de datos

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/datasources` | Lista (URL siempre enmascarada) |
| `POST` | `/api/datasources` | Crea: `name`, `dialect`, `url`, `execute`, `max_rows`, `timeout_seconds`, `privacy` |
| `PATCH` | `/api/datasources/{id}` | Actualiza; `url` solo se reemplaza si se envía |
| `DELETE` | `/api/datasources/{id}` | Elimina (no permitido si `managed_by = config`) |
| `POST` | `/api/datasources/{id}/test` | Prueba la conexión: `{ok, latency_ms, server_version, error?}` |

## Modelo semántico

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/datasources/{id}/semantic` | Versión vigente del modelo |
| `PUT` | `/api/datasources/{id}/semantic` | Publica una versión nueva (valida antes de guardar; 422 con la lista de errores) |
| `GET` | `/api/datasources/{id}/semantic/versions` | Historial |
| `POST` | `/api/datasources/{id}/semantic/import` | `multipart`: archivo `.sql` · `.csv` · `.xlsx` · `.yaml` · `.json`. Devuelve **vista previa** (modelo fusionado + diferencias); no guarda |
| `POST` | `/api/datasources/{id}/semantic/introspect` | Lee la base conectada y devuelve vista previa; no guarda |
| `POST` | `/api/datasources/{id}/semantic/suggest` | Sugerencias de IA para descripciones, sinónimos y roles vacíos |
| `GET` | `/api/datasources/{id}/semantic/export?format=yaml` | Exporta el modelo |
| `POST` | `/api/datasources/{id}/preview` | Métrica + período + dimensiones + filtros + rol → `{sql, summary_table, period, filters_applied}`, sin IA |
| `POST` | `/api/datasources/{id}/validate-sql` | SQL + rol → resultado del guardián (para pruebas) |

## Proveedores de IA

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/providers/catalog` | Catálogo: tipos, categoría, campos (nombre, tipo, obligatorio, secreto), modelos sugeridos, enlace a documentación |
| `GET` | `/api/providers` | Proveedores configurados (secretos enmascarados) |
| `POST` | `/api/providers` | Crea: `name`, `kind`, `model`, `config`, `secrets`, `params`, `tasks` |
| `PATCH` | `/api/providers/{id}` | Actualiza; un secreto solo cambia si se envía |
| `DELETE` | `/api/providers/{id}` | Elimina |
| `POST` | `/api/providers/{id}/test` | Prueba la conexión guardada |
| `POST` | `/api/providers/test` | Prueba una configuración **sin guardarla** |
| `GET` | `/api/providers/{id}/models` | Modelos disponibles, si la API del proveedor lo permite |
| `PUT` | `/api/providers/routing` | Asigna tareas (`planner`, `sql`, `answer`, `suggest`) y cadena de respaldo |

## Chat y conversaciones

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/chat/stream` | Envía un mensaje y recibe el turno por **SSE** |
| `POST` | `/api/chat/{turn_id}/cancel` | Cancela un turno en curso |
| `GET` | `/api/conversations` | Lista del usuario |
| `GET` | `/api/conversations/{id}` | Mensajes con sus eventos |
| `PATCH` | `/api/conversations/{id}` | Renombrar |
| `DELETE` | `/api/conversations/{id}` | Eliminar |

Cuerpo de `POST /api/chat/stream`:

```json
{
  "conversation_id": "7d0c…",
  "datasource_id": "a41e…",
  "message": "¿Cuánto vendí?",
  "provider_override": null,
  "view_as": null
}
```

`view_as` (`{role, attributes}`) solo lo pueden usar administradores, para probar permisos. Respuesta (`text/event-stream`):

```text
event: turn.started
data: {"turn_id":"f3…","conversation_id":"7d0c…"}

event: step
data: {"id":"understand","label":"Entendiendo la pregunta","status":"running"}

event: reasoning
data: {"text":"Preguntan cuánto vendieron: es la métrica ventas_netas. No mencionan período."}

event: clarification
data: {"question":"¿De qué período quieres ver las ventas?","options":["Hoy","Esta semana","Este mes","Mes pasado","Este año","Últimos 30 días"],"slot":"period"}

event: turn.completed
data: {"usage":{"tokens_in":1830,"tokens_out":142,"cost_usd":0.0031},"elapsed_ms":1240}
```

Todos los eventos: [FLUJO_CONVERSACIONAL.md](FLUJO_CONVERSACIONAL.md#eventos-de-streaming).

## Administración (M3)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/auth/login` | Correo + contraseña → JWT |
| `GET` | `/api/users` · `POST` · `PATCH` · `DELETE` | Usuarios |
| `PUT` | `/api/users/{id}/grants` | Rol y atributos por fuente de datos |
| `GET` | `/api/audit` | Auditoría con filtros (usuario, fuente, fecha, estado) |
| `GET` | `/api/audit/export` | Exporta CSV |

## Evaluación (M4)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/evals/runs` | Corre un set dorado contra uno o varios proveedores |
| `GET` | `/api/evals/runs` | Resultados: exactitud, latencia p50/p95, costo por proveedor |
