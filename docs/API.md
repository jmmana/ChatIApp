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

## Modelo semántico

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/datasources/{id}/semantic` | Versión vigente del modelo |
| `PUT` | `/api/v1/datasources/{id}/semantic` | Publica una versión nueva (solo administradores). Cuerpo `{base_version, model}`; `base_version` es la versión vigente que vio el cliente (`0` si no hay ninguna). Valida antes de guardar: 422 con `error.details.errors = [{path, message}]` y sin guardar; 409 `version_conflict` (con `details.current_version`) si alguien publicó antes. Para volver a una versión anterior, se publica su modelo como versión nueva |
| `GET` | `/api/v1/datasources/{id}/semantic/versions` | Historial (`version`, `created_by`, `created_at`), la más reciente primero |
| `GET` | `/api/v1/datasources/{id}/semantic/versions/{n}` | Una versión del historial con su modelo |
| `POST` | `/api/v1/datasources/{id}/semantic/import` | `multipart`: archivo `.sql` · `.csv` · `.xlsx` · `.yaml` · `.json`. El formato se detecta por la extensión. Devuelve **vista previa** `{model, diff, warnings}`; no guarda. `diff` trae `added` (`{path, kind}`), `changed` (`{path, field, before, after}`), `missing` (`{path, kind}`: no encontradas, no se borran) y `suggestions` (`{path, field, current, suggested}`: descripciones de la fuente que no pisan las escritas a mano). Extensión desconocida: 422 `unsupported_format`; archivo ilegible: 422 `invalid_file`. Solo administradores |
| `POST` | `/api/v1/datasources/{id}/semantic/introspect` | Lee la base conectada y devuelve vista previa; no guarda |
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

## Administración (M3)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Correo + contraseña → JWT |
| `GET` | `/api/v1/users` · `POST` · `PATCH` · `DELETE` | Usuarios |
| `PUT` | `/api/v1/users/{id}/grants` | Rol y atributos por fuente de datos |
| `GET` | `/api/v1/audit` | Auditoría con filtros (usuario, fuente, fecha, estado) |
| `GET` | `/api/v1/audit/export` | Exporta CSV |

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

Guía completa con ejemplos de backend, widget y SDKs: [INTEGRACION.md](INTEGRACION.md).

## Evaluación (M4)

| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/evals/runs` | Corre un set dorado contra uno o varios proveedores |
| `GET` | `/api/v1/evals/runs` | Resultados: exactitud, latencia p50/p95, costo por proveedor |
