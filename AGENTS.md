# Convenciones para agentes en ChatIApp

Este repositorio se desarrolla a partir de issues, en buena parte con agentes (WarCodex). Este archivo documenta las **convenciones** del repo: formato, pruebas, verificación e informes. El alcance de cada tarea lo define su issue.

La documentación en [`docs/`](docs/) es el contrato. Antes de escribir código, lee el issue completo y los documentos que enlaza.

## Entorno del agente

| Herramienta | Disponible | Cómo se verifica |
|---|---|---|
| Node 22, pnpm, npm | Sí | Ejecuta `pnpm install`, `pnpm run lint`, `pnpm run test` y `pnpm run build` en `frontend/` y `embed/` antes de terminar. Commitea `pnpm-lock.yaml` |
| Python, uv, ruff, mypy, pytest | **No** | Escribe el código y sus pruebas igual: el CI de GitHub ([`ci.yml`](.github/workflows/ci.yml)) los ejecuta en cada PR |
| PyPI | **No** | Declara las dependencias en `backend/pyproject.toml`. **No escribas `backend/uv.lock` a mano**: quien revisa el PR lo genera y aplica `ruff format` antes de fusionar |
| Postgres, MySQL, SQL Server, navegadores, proveedores de IA | **No** | Usa SQLite con la demo y el proveedor simulado (`kind: fake`). Los criterios que exigen servicios reales déjalos sin marcar en el PR y explica cómo se verifican |

## Reglas del repositorio

- **No modifiques nada en `.github/workflows/`.** Si la tarea necesita un workflow, escribe el YAML propuesto en la descripción del PR; lo aplica quien revisa.
- **Una tarea, un resultado.** No implementes otras tareas del backlog aunque estén cerca. Si dependes de algo que aún no existe, usa la interfaz mínima necesaria y dilo en el PR.
- Respeta la estructura de [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md#estructura-del-repositorio-objetivo). Todas las rutas HTTP van bajo **`/api/v1`**.
- No agregues dependencias que la tarea no necesite; si agregas una, justifícala en el PR.
- Nada de secretos, credenciales, URLs de conexión ni datos reales. Para datos usa `examples/ventas/` y la demo SQLite.
- El motor (`backend/app/engine/`) no importa nada de `backend/app/llm/`: se prueba sin red ni IA.
- **ChatIApp es una sola imagen** ([ADR 0008](docs/adr/0008-imagen-unica-con-sqlite.md)): el `Dockerfile` de la raíz construye la interfaz y el backend, y FastAPI sirve ambos. No agregues Dockerfiles por servicio, nginx ni contenedores obligatorios; la base de la app es SQLite en `/data` y el código debe funcionar también con PostgreSQL. Tu contenedor no tiene Docker: el CI construye la imagen y corre `scripts/smoke-image.sh`.
- **El guardián SQL es la librería [sqlguardllm](https://github.com/jmmana/sqlguardllm)** (`pip install sqlguardllm`, `import sqlguardllm`). No reimplementes sus reglas (solo lectura, tablas, columnas ocultas, funciones, filtros por rol, límite): arma su `Policy` desde el modelo semántico. Si le falta algo, se pide en su repositorio.

## Backend (Python)

- Python **3.12**, FastAPI, Pydantic v2, SQLAlchemy 2, sqlglot, LiteLLM. Gestión con `uv`.
- Tipos en todas las funciones públicas; el código debe pasar `ruff check`, `ruff format --check` (longitud 100) y `mypy app`.
- Pruebas con pytest en `backend/tests/`, en carpetas espejo de `app/`. Sin red: proveedor simulado y SQLite.
- Como no puedes ejecutar Python, revisa con especial cuidado imports, tipos, firmas y rutas de archivos de prueba antes de terminar.

## Frontend (TypeScript)

- React 19, TypeScript estricto, Vite, Tailwind CSS, shadcn/ui, TanStack Query.
- Scripts obligatorios en `package.json`: `dev`, `build`, `lint` y `test` (que ejecuta `vitest run`, sin modo observador).
- `package.json` declara `"packageManager": "pnpm@<versión exacta>"`, para que el contenedor del agente y el CI usen la misma versión vía corepack.
- Textos de la interfaz en español; colores con los tokens de [docs/INTERFAZ.md](docs/INTERFAZ.md#principios-de-diseño).

## Commits y pull requests

- Mensajes de commit en español, en imperativo, explicando el porqué.
- En la descripción del PR: los criterios de aceptación del issue con los cumplidos marcados y **cómo se verificó cada uno**; aparte, lo que no se pudo verificar en el contenedor y por qué.
- Si cambias un contrato (API, modelo semántico, eventos SSE, configuración), actualiza el documento de `docs/` en el mismo PR.

## Errores frecuentes de los PR

Lista viva: se completa con los errores que aparezcan en las revisiones para que no se repitan.

- **Si cambias dependencias de `backend/pyproject.toml`, no toques `backend/uv.lock`**: el CI fallará en `uv sync --locked` hasta que quien revisa genere el lock en la rama. Es esperado; dilo en el PR.
- **No escribas claves de prueba con forma real** (`sk-…`, `sk-ant-…`, `AKIA…`, `ghp_…`): el escáner de secretos bloquea la entrega aunque sean falsas. Usa `clave-de-prueba-1234` o arma el prefijo en tiempo de ejecución (`"sk" + "-ant-" + "prueba"`).
- **Toda ruta nueva bajo `/api/v1` exige sesión**: inclúyela con `dependencies=[Depends(get_current_user)]` (o `require_admin`). `tests/security/test_routes.py` falla si queda pública; en las pruebas de tu API usa un usuario autenticado o `dependency_overrides[get_current_user]`.
