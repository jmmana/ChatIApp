# ADR 0006 · Server-Sent Events para el streaming del turno

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

Un turno tarda varios segundos: entender, resolver, validar, ejecutar, redactar. Mostrar un spinner esconde justo lo que genera confianza: el razonamiento. La interfaz necesita recibir eventos tipados mientras ocurren (pasos, aclaración, SQL, resultado, texto de la respuesta).

## Decisión

`POST /api/v1/chat/stream` responde con `text/event-stream` (Server-Sent Events). Cada evento tiene `event:` con su tipo y `data:` con JSON. El frontend consume el flujo con `fetch` y un lector de SSE (no `EventSource`, que no permite `POST` ni cabeceras de autorización). Cancelar es `POST /api/v1/chat/{turn_id}/cancel`.

nginx sirve `/api` con `proxy_buffering off` para que los eventos no se acumulen.

> **Nota (2026-11-25):** desde el [ADR 0008](0008-imagen-unica-con-sqlite.md) no hay nginx en la imagen; uvicorn entrega los eventos directamente. La respuesta lleva `X-Accel-Buffering: no` y `Cache-Control: no-cache` para que un proxy que pongas delante tampoco los acumule.

## Consecuencias

- ✅ HTTP normal: pasa por proxies, balanceadores y autenticación por cabecera sin infraestructura adicional.
- ✅ Unidireccional, que es exactamente lo que necesita un turno; el siguiente mensaje es otra petición.
- ✅ Fácil de probar: el cuerpo es texto.
- ⚠️ Algunos proxies corporativos acumulan respuestas; se documenta la configuración y se envía un comentario de keep-alive cada 15 s.

## Alternativas consideradas

- **WebSockets.** Bidireccional, que no hace falta; complica proxies y autenticación.
- **Sondeo (polling).** Más latencia y más carga, y la respuesta pierde la sensación de «en vivo».
