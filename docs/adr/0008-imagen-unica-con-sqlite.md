# ADR 0008 · Una sola imagen con SQLite por defecto

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

El diseño inicial repartía ChatIApp en cuatro contenedores: `web` (nginx con la interfaz), `api` (FastAPI), `app-db` (PostgreSQL) y `ollama` opcional. Para probar la app o integrarla en otro producto había que levantar al menos tres servicios, configurar una contraseña de base de datos y esperar a que PostgreSQL arrancara.

La base de datos propia de ChatIApp guarda poco y se escribe poco: configuración, fuentes, credenciales cifradas, modelos semánticos versionados, conversaciones y auditoría. Cada turno escribe unas pocas filas. Una instalación típica tiene una sola réplica.

## Decisión

1. **Una sola imagen** `ghcr.io/jmmana/chatiapp`, construida con un `Dockerfile` multietapa en la raíz del repositorio. La etapa de Node construye la interfaz con pnpm; la imagen final es Python 3.12 y FastAPI sirve la interfaz en `/`, la API en `/api/v1` y el script del chat embebido. Las rutas de la interfaz devuelven `index.html`; una ruta `/api/...` desconocida devuelve 404 en JSON.
2. **SQLite por defecto** en `/data/chatiapp.db` (`CHATIAPP_DATABASE_URL=sqlite:////data/chatiapp.db`), con modo WAL y claves foráneas activas. `/data` es un volumen: ahí viven la base, la demo de ventas y, si no defines `CHATIAPP_SECRET_KEY`, la llave de cifrado que la imagen genera en el primer arranque (`/data/secret.key`, permisos 600).
3. **PostgreSQL es opcional:** basta cambiar `CHATIAPP_DATABASE_URL`. Se recomienda cuando haya más de una réplica o mucha concurrencia de escritura. Las migraciones de Alembic se prueban en ambos motores.
4. **Ollama sigue aparte**, como perfil opcional `local-ai` de `docker-compose.yml`, igual que `postgres`.
5. Al arrancar, la imagen aplica las migraciones y genera la demo si no existe; corre con un usuario sin privilegios y declara un `HEALTHCHECK` a `/api/v1/health`.

```bash
docker run -p 8080:8080 -v chatiapp:/data -e ANTHROPIC_API_KEY=… ghcr.io/jmmana/chatiapp
```

## Consecuencias

- ✅ Probar ChatIApp es un `docker run`. No hay contraseñas de base ni servicios que esperar.
- ✅ Integrar sin interfaz usa la misma imagen; no hay que elegir entre `chatiapp-api` y `chatiapp-web`.
- ✅ Sin nginx no hace falta apagar el buffering para SSE: uvicorn entrega los eventos directamente.
- ✅ Respaldar una instalación es copiar el volumen `/data`.
- ⚠️ Con la llave generada, quien tenga el volumen puede descifrar las credenciales. En producción conviene definir `CHATIAPP_SECRET_KEY` desde un gestor de secretos.
- ⚠️ SQLite admite un solo escritor a la vez. Con WAL alcanza para una réplica; para varias réplicas hay que usar PostgreSQL. La guía de despliegue y el chart de Helm lo dicen así.
- ⚠️ La imagen es algo más grande porque incluye los archivos estáticos de la interfaz (unos pocos MB).
- ⚠️ El código no puede usar funciones exclusivas de PostgreSQL en la base de la app; las pruebas de migraciones corren contra los dos motores.

## Alternativas consideradas

- **Cuatro contenedores con PostgreSQL obligatorio** (el diseño anterior). Más cercano a una instalación grande, pero caro para el caso más común: probar e integrar.
- **Dos imágenes (`chatiapp-api` y `chatiapp-web`) con SQLite.** Ahorra PostgreSQL pero mantiene nginx y dos artefactos que versionar juntos.
- **Base embebida distinta (DuckDB, archivos JSON).** DuckDB está pensada para análisis, no para muchas escrituras pequeñas; los archivos JSON no dan transacciones ni migraciones.
