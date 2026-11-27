# Observabilidad

Para diagnosticar por qué un turno fue lento, caro o falló. Código en `backend/app/observability/`.

## Configuración

| Variable | Por defecto | Efecto |
|---|---|---|
| `CHATIAPP_LOG_LEVEL` | `INFO` | Nivel de los logs |
| `CHATIAPP_LOG_FORMAT` | `json` | `json` (una línea por registro) o `text` |
| `CHATIAPP_OTEL_ENDPOINT` | vacío | Base OTLP/HTTP (`http://colector:4318`). Sin ella no se exportan trazas |
| `CHATIAPP_OTEL_SERVICE_NAME` | `chatiapp` | `service.name` de las trazas |
| `CHATIAPP_METRICS_TOKEN` | vacío | Sin token, `/metrics` responde 404 (deshabilitada). Con token exige `Authorization: Bearer <token>` (401 si no coincide) |

## Logs

JSON por línea con `ts`, `level`, `logger`, `message` y, dentro de un turno, `turn_id`,
`conversation_id`, `user` (id interno o externo, nunca el correo) y `stage`. Los registros de etapa
añaden `status`, `duration_ms`, `tokens_in` y `tokens_out`.

El formateador solo emite campos de una lista cerrada: una fila o un secreto pasado en `extra=` se
descarta. El mensaje tapa credenciales con forma conocida y de las excepciones solo salen el tipo y
la pila, sin su mensaje.

## Trazas

Un span `chatiapp.turn` por turno con un hijo por etapa: `planner`, `verify`, `period`, `builder`,
`compare`, `guard`, `repair`, `executor` y `answer`.

- Turno: `chatiapp.turn_id`, `chatiapp.conversation_id`, `chatiapp.user`, `chatiapp.role`,
  `chatiapp.outcome` (`ok`, `clarification`, `error`, `cancelled`), tokens y costo totales.
- Etapas con IA (`planner`, `repair`, `answer`): `llm.provider`, `llm.model`, `llm.tokens.input`,
  `llm.tokens.output`, `llm.cost_usd`.
- Etapas con consulta (`builder`, `guard`, `executor`, `compare`): `db.tables`.

Nunca se registran SQL, preguntas ni filas.

## Métricas

`GET /metrics` (formato Prometheus, fuera de `/api/v1`; está deshabilitada (404) mientras no
definas `CHATIAPP_METRICS_TOKEN`; con él exige `Authorization: Bearer <token>`):

| Métrica | Tipo | Etiquetas |
|---|---|---|
| `chatiapp_turns_total` | contador | `outcome` |
| `chatiapp_guard_rejections_total` | contador | |
| `chatiapp_provider_errors_total` | contador | `provider` |
| `chatiapp_turn_duration_seconds` | histograma | |
| `chatiapp_stage_duration_seconds` | histograma | `stage` |
| `chatiapp_llm_tokens_total` | contador | `direction` (`input`, `output`) |
| `chatiapp_llm_cost_usd_total` | contador | |

## Verlo en local

```bash
echo CHATIAPP_OTEL_ENDPOINT=http://otel-collector:4318 >> .env
docker compose --profile observability up --build
```

Jaeger queda en <http://localhost:16686> (servicio `chatiapp`). El colector usa
`observability/otel-collector.yaml`.
