# SDKs de ChatIApp

| Paquete | Carpeta | Registro |
|---|---|---|
| `chatiapp` | [`python/`](python/) | PyPI |
| `@chatiapp/client` | [`typescript/`](typescript/) | npm |

Cada SDK tiene dos capas:

- **Generada** desde [`docs/openapi/v1.json`](../docs/openapi/v1.json): los modelos de toda la API (`python/chatiapp/_generated.py`, `typescript/src/generated/types.ts`). Se regeneran con `node sdks/scripts/generate.mjs` (sin dependencias); `--check` falla si están desactualizados, y es lo que corre el CI.
- **Escrita a mano**: el cliente de chat (`chat`, `chat_stream`, `cancel`), los eventos SSE tipados y el ayudante de tokens de sesión (`create_embed_session`). El contrato OpenAPI no describe el stream ni la respuesta de `POST /chat`; se documentan en [FLUJO_CONVERSACIONAL.md](../docs/FLUJO_CONVERSACIONAL.md#eventos-de-streaming) y [INTEGRACION.md](../docs/INTEGRACION.md#sin-streaming).

Cuando cambie `docs/openapi/v1.json`, regenera y commitea. Las pruebas `test_demo.py` y `demo.test.ts` corren contra una instancia real si defines `CHATIAPP_DEMO_URL` y `CHATIAPP_DEMO_API_KEY`.

## Publicación

El workflow `.github/workflows/sdks.yml` regenera y comprueba los SDKs en cada PR y, al publicar una release, los sube a PyPI y npm. Necesita los secretos `PYPI_API_TOKEN` y `NPM_TOKEN` del repositorio. La versión de cada paquete (`python/pyproject.toml`, `typescript/package.json`) debe coincidir con la etiqueta de la release.
