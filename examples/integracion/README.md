# App anfitriona de ejemplo

Una app mínima (FastAPI) que integra el chat de ChatIApp como lo describe [docs/INTEGRACION.md](../../docs/INTEGRACION.md#chat-embebido). Cópiala y cámbiale el login por el de tu app.

| Pieza | Dónde |
|---|---|
| Login de prueba (usuarios `ana` → sucursal 1, `bruno` → sucursal 2) | `app.py`, `POST /login` |
| `POST /chatiapp-token`: cambia la API key por un token de sesión del usuario con sesión | `app.py` |
| Página con `<chatiapp-chat>` | `app.py`, `GET /` |

La API key solo existe en el servidor de la app anfitriona. El navegador recibe la página, el script del widget y un token de 15 minutos atado al usuario, a la fuente y al origen.

## Levantarla

```bash
docker compose --profile integracion up --build
```

1. Compose levanta ChatIApp con la demo «Ventas», crea una API key (`embed`, rol fijo `gerente_sucursal`, solo la fuente de la demo, solo el origen `http://localhost:8000`) con `preparar.sh` y arranca la app anfitriona.
2. ChatIApp necesita un proveedor de IA para responder. Entra a <http://localhost:8080>, crea el administrador (`CHATIAPP_ADMIN_EMAIL` y `CHATIAPP_ADMIN_PASSWORD` en `.env`) y agrega uno en **Proveedores**; para probar sin IA real, usa el tipo `fake`.
3. Abre <http://localhost:8000> y entra como `ana` (`clave-ana-1234`) o `bruno` (`clave-bruno-1234`). Pregunta «ventas por sucursal este año»: cada uno ve solo su sucursal.

Puertos: `CHATIAPP_PORT` (8080) e `INTEGRACION_PORT` (8000). Si cambias el segundo, la key se crea con el origen nuevo la primera vez; si ya existe, bórrala (`docker compose exec chatiapp chatiapp keys revoke <chia_id>`) y borra `/data/integracion` del volumen para que se genere otra.

## Variables de la app anfitriona

| Variable | Para qué |
|---|---|
| `CHATIAPP_URL` | Cómo llega el servidor a ChatIApp (red interna) |
| `CHATIAPP_PUBLIC_URL` | Cómo llega el navegador a ChatIApp (el script y las preguntas) |
| `CHATIAPP_API_KEY` / `CHATIAPP_API_KEY_FILE` | La API key de servidor, directa o desde un archivo montado |
| `CHATIAPP_DATASOURCE` / `CHATIAPP_DATASOURCE_FILE` | UUID de la fuente (o su `id` si viene de `chatiapp.yaml`) |
| `HOST_ORIGIN` | Origen desde el que el navegador abre la app; debe estar entre los orígenes permitidos de la key |

## Sin Docker

```bash
pip install -r requirements.txt
CHATIAPP_API_KEY=… CHATIAPP_DATASOURCE=<uuid> uvicorn app:app --port 8000
```

## Solo para el ejemplo

- Los usuarios y contraseñas están en el código y la sesión es una cookie firmada con una clave fija (`HOST_SECRET`). Usa el login real de tu app.
- `preparar.sh` deja la API key en un archivo del volumen de ChatIApp, legible por la app anfitriona. En producción, guárdala en tu gestor de secretos.

## Prueba

`backend/tests/examples/test_integracion.py` corre la app contra ChatIApp con la demo y verifica que dos usuarios de sucursales distintas ven resultados distintos y que la API key no aparece en nada de lo que recibe el navegador.
