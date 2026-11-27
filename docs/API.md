# API

> Borrador del contrato. FastAPI genera la especificación OpenAPI completa en `/api/v1/docs` cuando el backend exista; este documento fija los recursos y el streaming para que backend y frontend avancen en paralelo.

Convenciones: JSON, prefijo `/api/v1`, identificadores UUID, errores con forma `{"error": {"code": "…", "message": "…", "details": {…}}}`. Política de versiones: [INTEGRACION.md](INTEGRACION.md#versionado-de-la-api).

## Autenticación

Todas las rutas salvo `/api/v1/health` y `/api/v1/auth/*` exigen `Authorization: Bearer <credencial>` desde el hito M3 (antes, modo desarrollo sin login). Tres tipos de credencial:

| Credencial | Quién la usa | Qué puede |
|---|---|---|
| JWT de usuario | La interfaz de ChatIApp, tras el login | Lo que permita el usuario (administrador o no) |
| API key `chia_…` | El backend de una app que integra ChatIApp | Lo que permitan sus alcances, fuentes y roles; declara el usuario final en `user` |
| Token de sesión | El chat embebido en el navegador | Solo chat, en una fuente, como un usuario, desde un origen, por 15 minutos |

Detalle y ejemplos: [INTEGRACION.md](INTEGRACION.md).

### Sesión de usuario (JWT)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/auth/login` | `{email, password}` → `{access_token, token_type, expires_in, user}`; el refresh token se entrega en la cookie `HttpOnly` `chatiapp_refresh` (`SameSite=Strict`, ruta `/api/v1/auth`, 7 días) |
| `POST` | `/api/v1/auth/refresh` | Con la cookie, emite un nuevo JWT y rota la cookie |
| `POST` | `/api/v1/auth/logout` | Borra la cookie |
| `GET` | `/api/v1/auth/me` | Usuario autenticado |

- El JWT (HS256, firmado con `CHATIAPP_SECRET_KEY`) dura 15 minutos; la interfaz lo guarda solo en memoria.
- Las rutas de administración exigen `is_admin` (403 `forbidden` si no); sin credencial válida, 401.
- 5 intentos fallidos por correo en 15 minutos bloquean el correo durante el resto de la ventana (429 `too_many_attempts`). El contador es en memoria, por proceso.
- Primer arranque: si no hay ningún administrador y existen `CHATIAPP_ADMIN_EMAIL` y `CHATIAPP_ADMIN_PASSWORD`, se crea ese administrador.
- `CHATIAPP_COOKIE_SECURE` (por defecto `true`) controla el atributo `Secure` de la cookie; ponla en `false` solo en desarrollo sin HTTPS.

## Salud

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/health` | Estado, versión y conectividad con la BD de la app |

## Fuentes de datos

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/datasources` | Lista (URL siempre enmascarada) |
| `POST` | `/api/v1/datasources` | Crea: `name`, `dialect`, `url`, `execute`, `max_rows`, `timeout_seconds`, `privacy` |
| `PATCH` | `/api/v1/datasources/{id}` | Actualiza; `url` solo se reemplaza si se envía |
| `DELETE` | `/api/v1/datasources/{id}` | Elimina (409 `managed_by_config` si `managed_by = config`; igual en `PATCH`) |
| `POST` | `/api/v1/datasources/{id}/test` | Prueba la conexión: `{ok, latency_ms, server_version, error?}`; `error` es `{kind, message}` con `kind` en `auth`, `network`, `driver_missing` o `unknown` (si falta el driver, el mensaje indica el extra: `uv sync --extra sqlserver`) |

Ver la lista exige sesión; crear, cambiar, borrar y probar la conexión exigen administrador (403 `forbidden` si no).

## Métricas sugeridas

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/datasources/{id}/metrics` | Métricas que el rol del usuario puede consultar, para sugerir preguntas. Basta con sesión (no exige administrador) |

Responde `{metrics: [{name, label, description, requires_period, default_period, dimensions}]}`. Solo incluye las métricas cuya tabla no está oculta para el rol del usuario (el rol de su permiso; para administradores sin permiso, el rol por defecto del modelo). `dimensions` son nombres para mostrar (primer sinónimo de la columna o su nombre legible), sin las de tablas o columnas ocultas. No trae SQL, expresiones, filtros, tablas ni columnas físicas. Una fuente inexistente, sin modelo o sin permiso para el usuario responde la misma `404 datasource_not_found`.

## Modelo semántico

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/datasources/{id}/semantic` | Versión vigente del modelo |
| `PUT` | `/api/v1/datasources/{id}/semantic` | Publica una versión nueva (solo administradores). Cuerpo `{base_version, model}`; `base_version` es la versión vigente que vio el cliente (`0` si no hay ninguna). Valida antes de guardar: 422 con `error.details.errors = [{path, message}]` y sin guardar; 409 `version_conflict` (con `details.current_version`) si alguien publicó antes. Para volver a una versión anterior, se publica su modelo como versión nueva |
| `GET` | `/api/v1/datasources/{id}/semantic/versions` | Historial (`version`, `created_by`, `created_at`), la más reciente primero |
| `GET` | `/api/v1/datasources/{id}/semantic/versions/{n}` | Una versión del historial con su modelo |
| `POST` | `/api/v1/datasources/{id}/semantic/import` | `multipart`: archivo `.sql` · `.csv` · `.xlsx` · `.yaml` · `.json`. El formato se detecta por la extensión. Devuelve **vista previa** `{model, diff, warnings}`; no guarda. `diff` trae `added` (`{path, kind}`), `changed` (`{path, field, before, after}`), `missing` (`{path, kind}`: no encontradas, no se borran) y `suggestions` (`{path, field, current, suggested}`: descripciones de la fuente que no pisan las escritas a mano). Extensión desconocida: 422 `unsupported_format`; archivo ilegible: 422 `invalid_file`. Solo administradores |
| `POST` | `/api/v1/datasources/{id}/semantic/introspect` | Lee la base conectada y devuelve vista previa (`schemas`, `tables`, `relationships`, `warnings`); no guarda. Cuerpo opcional: `schemas` (lista), `table_pattern` (comodines `*` y `?`), `sample_values` (hasta 20 valores de columnas de texto de baja cardinalidad; solo con privacidad `samples`, y cada consulta pasa por el guardián). Con más de 500 tablas responde `422 too_many_tables`: hay que filtrar. Solo administración |
| `POST` | `/api/v1/datasources/{id}/semantic/suggest` | Sugerencias de IA para descripciones, sinónimos y roles vacíos |
| `GET` | `/api/v1/datasources/{id}/semantic/export?format=yaml` | Exporta el modelo vigente (`format=yaml` o `json`); reimportarlo da un modelo idéntico |
| `POST` | `/api/v1/datasources/{id}/preview` | Cuerpo `{metric, period?, dimensions?, filters?, granularity?, view_as?}` → `{sql, metric, role, summary_table, reason, period, filters_applied, guard}`, sin IA. Errores de catálogo, de período o de plan: `422` |
| `POST` | `/api/v1/datasources/{id}/validate-sql` | Cuerpo `{sql, view_as?}` → resultado del guardián `{allowed, sql, tables, violations, role}` (para pruebas; solo administradores, porque revela qué columnas están ocultas) |

Ambas usan la última versión del modelo semántico y el rol y atributos del permiso (`grant`) del usuario; `view_as` (`{role, attributes}`) solo lo usan administradores (`403` para los demás). Sin modelo publicado responden `404`.

Leer y publicar el modelo exigen administrador (403 `forbidden` si no): el modelo incluye columnas ocultas y filtros por rol.

## Proveedores de IA

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/providers/catalog` | Catálogo: tipos, categoría, campos (nombre, tipo, obligatorio, secreto), modelos sugeridos, enlace a documentación |
| `GET` | `/api/v1/providers` | Proveedores configurados (secretos enmascarados) |
| `POST` | `/api/v1/providers` | Crea: `name`, `kind`, `model`, `config`, `secrets`, `params`, `tasks` |
| `PATCH` | `/api/v1/providers/{id}` | Actualiza; un secreto solo cambia si se envía |
| `DELETE` | `/api/v1/providers/{id}` | Elimina |
| `POST` | `/api/v1/providers/{id}/test` | Prueba la conexión guardada |
| `POST` | `/api/v1/providers/test` | Prueba una configuración **sin guardarla** |
| `GET` | `/api/v1/providers/{id}/models` | Modelos disponibles, si la API del proveedor lo permite |
| `PUT` | `/api/v1/providers/routing` | Asigna tareas (`planner`, `sql`, `answer`, `suggest`) y cadena de respaldo. Cuerpo: `{"tasks": {"sql": "<id>"}, "fallback": ["<id>"]}` |

Los secretos se guardan cifrados y se devuelven enmascarados (`secrets: {"api_key": "…1234"}`). `config` y `secrets` se validan contra los campos del catálogo del `kind` (422 `invalid_provider`). Solo hay un proveedor `is_default`. Los proveedores con `managed_by = "config"` no se editan ni se eliminan desde la API (409 `managed_by_config`); un nombre repetido da 409 `name_taken`.

`test` (ambas rutas) responde `{"ok", "latency_ms", "error_kind", "message"}`; `error_kind` es `auth`, `quota`, `model_not_found`, `timeout`, `network` o `provider_error` (`null` si `ok`). El cuerpo de `POST /providers/test` es `kind`, `model`, `config`, `secrets` y `params`. Ninguna prueba dura más de 15 s. `models` responde `{"supported", "models", "error_kind", "message"}`: lista modelos en APIs compatibles con OpenAI, Anthropic, Gemini y Ollama; en las demás, `supported: false`.

## Chat y conversaciones

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/chat/stream` | Envía un mensaje y recibe el turno por **SSE** |
| `POST` | `/api/v1/chat` | Igual, sin streaming: devuelve el turno completo (`answered` o `needs_clarification`) en un JSON. Pensado para integraciones |
| `POST` | `/api/v1/chat/{turn_id}/cancel` | Cancela un turno en curso |
| `GET` | `/api/v1/conversations` | Lista del usuario |
| `GET` | `/api/v1/conversations/{id}` | Mensajes con sus eventos |
| `PATCH` | `/api/v1/conversations/{id}` | Renombrar |
| `DELETE` | `/api/v1/conversations/{id}` | Eliminar |

Cuerpo de `POST /api/v1/chat/stream`:

```json
{
  "conversation_id": "7d0c…",
  "datasource_id": "a41e…",
  "message": "¿Cuánto vendí?",
  "provider_override": null,
  "view_as": null,
  "user": null
}
```

- `datasource_id` acepta el UUID o el `id` declarado en `chatiapp.yaml` (por ejemplo `"ventas"`).
- `view_as` (`{role, attributes}`) solo lo pueden usar administradores, para probar permisos.
- `user` (`{id, role, attributes}`) es **obligatorio con API key** y se ignora con otras credenciales: es el usuario final en cuyo nombre pregunta la app que integra ([INTEGRACION.md](INTEGRACION.md#identidad-del-usuario-final)).

Respuesta (`text/event-stream`):

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

- La respuesta lleva `Cache-Control: no-cache` y `X-Accel-Buffering: no`, y cada 15 s sin eventos envía un comentario `: keep-alive`.
- Sin `conversation_id` se crea una conversación (su título son los primeros 60 caracteres del mensaje). Si se envía, debe ser del usuario y de la misma fuente de datos (`404 conversation_not_found`, `409 datasource_mismatch`).
- Sin `provider_override` se usa el proveedor por defecto (`422 no_provider` si no hay ninguno).
- `POST /api/v1/chat/{turn_id}/cancel` (el `turn_id` llega en `turn.started`) detiene el turno en curso del usuario y responde `{"turn_id", "status": "cancelled"}`; el stream termina con `error` `{code: "cancelled", recoverable: true}` y no emite `turn.completed`. Un turno inexistente o ya terminado responde `404 turn_not_found`.

`POST /api/v1/chat` (sin streaming), además de lo descrito en [INTEGRACION.md](INTEGRACION.md):

- `status` es `rejected` cuando el error es `sql_rejected` o `user_config` (el guardián o la configuración rechazó el turno) y `error` en cualquier otro fallo.
- Tiempo máximo del turno: `CHATIAPP_CHAT_TIMEOUT_SECONDS` (por defecto 120). Si se supera responde **504** `turn_timeout` y el turno se cancela.

Conversaciones: cada usuario ve solo las suyas (una ajena responde `404`).

- `GET /api/v1/conversations` → `[{id, title, datasource_id, created_at}]`, las más recientes primero.
- `GET /api/v1/conversations/{id}` → lo anterior más `messages: [{id, role, content, events, created_at}]`. `events` guarda los eventos del turno del asistente (sin `answer.delta`) para reconstruir la conversación.
- `PATCH /api/v1/conversations/{id}` con `{"title"}` renombra; `DELETE` responde `204` y borra también sus mensajes.

## Administración (M3)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Correo + contraseña → JWT |
| `GET` | `/api/v1/users` · `POST` · `PATCH` · `DELETE` | Usuarios |
| `PUT` | `/api/v1/users/{id}/grants` | Rol y atributos por fuente de datos |
| `GET` | `/api/v1/audit` | Auditoría (solo administradores), más reciente primero. Filtros: `user_id`, `external_user_id`, `datasource_id`, `api_key_id`, `status` (`ok`, `rejected`, `error`), `date_from`, `date_to` (fechas `AAAA-MM-DD`, ambas inclusivas). Paginada con `page` y `page_size` (máx. 200) → `{items, total, page, page_size}` |
| `GET` | `/api/v1/audit/export` | Exporta en CSV (UTF-8, hasta 50 000 filas) con los mismos filtros; las celdas que empiezan con `=`, `+`, `-` o `@` se neutralizan |

### Usuarios y permisos por fuente

Todas las rutas de `/api/v1/users` exigen un administrador. `POST` recibe `{email, password, is_admin?}` (contraseña de 8 o más caracteres; 409 si el correo ya existe). `PATCH` cambia `email`, `password` o `is_admin`. No se puede eliminar al propio usuario ni dejar el sistema sin administradores (409).

`PUT /api/v1/users/{id}/grants` **reemplaza** los permisos del usuario:

```json
{ "grants": [
  { "datasource_id": "…", "role": "gerente_sucursal", "attributes": { "sucursales": [1, 2] } }
] }
```

- **422** `unknown_role`: el rol no existe en el modelo semántico vigente de la fuente.
- **422** `missing_attributes`: faltan (o están vacíos) atributos que exigen los filtros del rol (`{user.x}`).
- **404** si la fuente no existe. Las fuentes que no aparecen en la lista quedan sin acceso.

Al consultar una fuente (chat o vista previa), el rol y los atributos salen del permiso del usuario autenticado. Sin permiso: **403** `no_access` (los administradores usan el rol por defecto del modelo). `view_as` solo lo aceptan los administradores; los demás reciben **403** `view_as_forbidden`.

## Integraciones (M3)

| Método | Ruta | Credencial | Descripción |
|---|---|---|---|
| `GET` | `/api/v1/api-keys` | Administrador | Lista: nombre, prefijo visible, alcances, fuentes, roles, orígenes, último uso, consumo |
| `POST` | `/api/v1/api-keys` | Administrador | Crea una key; el secreto se devuelve **una sola vez** |
| `PATCH` | `/api/v1/api-keys/{id}` | Administrador | Cambia alcances, fuentes, roles, orígenes, límites o expiración |
| `POST` | `/api/v1/api-keys/{id}/revoke` | Administrador | Revoca la key y todos sus tokens de sesión al instante |
| `POST` | `/api/v1/embed/sessions` | API key con alcance `embed` | `{datasource, origin, user, ttl_seconds?}` → `{token, expires_at}` para el chat embebido |
| `GET` | `/embed/v1/chatiapp.js` | Pública | Script del chat embebido (web component) |
| `GET` | `/api/v1/openapi.json` | Pública | Especificación OpenAPI de la versión `v1` |

**Token de sesión** (`POST /embed/sessions`): `ttl_seconds` por defecto 900, máximo 3600 (422 fuera de rango). `origin` debe estar en los orígenes permitidos de la key (**403** `origin_not_allowed`); la fuente, el rol y los atributos se validan igual que en las llamadas con API key. El token es un JWT con usuario, fuente, rol, atributos, origen, id de la key y alcance `chat`, y solo se acepta en `POST /chat/stream`, `POST /chat/{turn_id}/cancel`, `GET /conversations` y `GET /conversations/{id}`; el resto responde 401. Con token:

- El `Origin` de cada petición debe ser el del token; si falta o es otro, **403** `origin_not_allowed`. CORS solo se concede a los orígenes permitidos de las keys vivas con alcance `embed`.
- Expirado: **401** `token_expired` (el widget pide otro a tu backend). Key revocada, vencida o sin alcance `embed`: **401** `invalid_api_key`, en la siguiente petición.
- Otra fuente distinta de la del token: **403** `datasource_not_allowed`. Las conversaciones son las de la key y el usuario del token; las ajenas responden 404.

Guía completa con ejemplos de backend, widget y SDKs: [INTEGRACION.md](INTEGRACION.md).

## Evaluación (M4)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/evals/runs` | Lanza una corrida del set dorado contra uno o varios proveedores (**202**) |
| `GET` | `/api/v1/evals/runs` | Corridas, la más reciente primero, con su avance y su informe |
| `GET` | `/api/v1/evals/runs/{id}` | Una corrida |

Solo administradores. `POST` recibe `{"provider_ids": [...], "max_calls": N}`; `max_calls` es obligatorio si algún proveedor no es `fake` y debe cubrir las llamadas previstas (**422** `max_calls_required`, con `details.planned_calls`). Solo corre una evaluación a la vez (**409** `eval_in_progress`). Cada corrida devuelve `status` (`running | done | error`), `cases_done`, `cases_total`, `error` y, al terminar, `report`: el informe de `app.eval.report` con exactitud (0 a 1), latencia p50/p95, tokens, costo y los casos fallidos con su SQL esperado y obtenido. El estado de las corridas vive en memoria y se pierde al reiniciar; cada proveedor deja además su `EVAL_RUN` en la base. Para asignar un proveedor a una tarea se usa `PUT /api/v1/providers/routing`.
