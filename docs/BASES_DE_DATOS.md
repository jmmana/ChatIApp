# Bases de datos

ChatIApp se conecta con [SQLAlchemy 2](https://www.sqlalchemy.org/) y habla cada dialecto con [sqlglot](https://github.com/tobymao/sqlglot). El motor arma el SQL en el dialecto de la fuente y el guardián lo valida en ese mismo dialecto.

## Motores soportados

| Motor | Dialecto sqlglot | Driver (extra de instalación) | URL de ejemplo |
|---|---|---|---|
| PostgreSQL | `postgres` | `psycopg` (`postgres`) | `postgresql+psycopg://chatiapp_ro:***@host:5432/ventas` |
| Amazon Redshift | `redshift` | `psycopg` (`postgres`) | `postgresql+psycopg://…:5439/dev` |
| SQL Server / Azure SQL | `tsql` | `pyodbc` (`sqlserver`) | `mssql+pyodbc://chatiapp_ro:***@host/ventas?driver=ODBC+Driver+18+for+SQL+Server` |
| MySQL / MariaDB | `mysql` | `pymysql` (`mysql`) | `mysql+pymysql://chatiapp_ro:***@host:3306/ventas` |
| Oracle | `oracle` | `oracledb` (`oracle`) | `oracle+oracledb://chatiapp_ro:***@host:1521/?service_name=VENTAS` |
| Snowflake | `snowflake` | `snowflake-sqlalchemy` (`snowflake`) | `snowflake://usuario:***@cuenta/BD/ESQUEMA?warehouse=WH` |
| Google BigQuery | `bigquery` | `sqlalchemy-bigquery` (`bigquery`) | `bigquery://proyecto/dataset` |
| SQLite | `sqlite` | incluido | `sqlite:///./demo/ventas.db` |

Los drivers son extras opcionales: se instala solo lo que se usa.

## Diferencias de dialecto que resuelve el motor

Verificado con sqlglot 30.35 parseando y regenerando SQL en cada dialecto (ida y vuelta). Las pruebas contra motores reales llegan con la tarea de integración multimotor del backlog.

| Motor | Truncar al mes | Literal de fecha en filtros | Límite de filas |
|---|---|---|---|
| SQLite | `STRFTIME('%Y-%m-01', col)` | `'2026-11-01'` (texto ISO) | `LIMIT n` |
| PostgreSQL | `DATE_TRUNC('MONTH', col)` | `CAST('2026-11-01' AS DATE)` | `LIMIT n` |
| MySQL / MariaDB | `DATE_FORMAT(col, '%Y-%m-01')` | `'2026-11-01'` | `LIMIT n` |
| SQL Server | `DATEFROMPARTS(YEAR(col), MONTH(col), 1)` | `'20261101'` | `TOP n` |
| Oracle | `TRUNC(col, 'MONTH')` | `TO_DATE('2026-11-01', 'YYYY-MM-DD')` | `FETCH FIRST n ROWS ONLY` |
| Snowflake | `DATE_TRUNC('MONTH', col)` | `CAST('2026-11-01' AS DATE)` | `LIMIT n` |
| BigQuery | `DATE_TRUNC(col, MONTH)` | `CAST('2026-11-01' AS DATE)` o `TIMESTAMP` según la columna | `LIMIT n` |

### Trampas conocidas

- **SQLite no tiene tipo fecha.** `CAST('2026-11-01' AS DATE)` devuelve `2026` (afinidad numérica; comprobado con `sqlite3`). Por eso en SQLite los límites se comparan como **texto ISO**, que ordena bien si las fechas se guardan en ISO.
- **SQL Server y el idioma de la sesión.** Con columnas `datetime`, el literal `'2026-11-01'` se interpreta según `SET LANGUAGE` / `SET DATEFORMAT` (con `british` puede leerse como año-día-mes). El formato `'20261101'` es siempre inequívoco. `DATETRUNC` solo existe desde SQL Server 2022, así que el motor usa `DATEFROMPARTS` para ser compatible con versiones anteriores.
- **Oracle y `NLS_DATE_FORMAT`.** Un literal de texto depende de la configuración de la sesión; sqlglot genera `TO_DATE` con formato explícito. `FETCH FIRST` requiere Oracle 12c o superior.
- **BigQuery no compara `DATE` con `TIMESTAMP`.** El tipo del literal debe coincidir con el de la columna; el motor lo toma del `type` de la columna en el modelo semántico. Además, `DATE_TRUNC` lleva los argumentos en otro orden.
- **MySQL no tiene `DATE_TRUNC`.** `DATE_FORMAT` devuelve texto; ordena bien porque el formato es ISO.
- **Zonas horarias.** Si la columna de tiempo es `timestamp` en UTC, los límites del período se convierten desde la zona horaria del negocio antes de comparar.

## Usuario de solo lectura

El guardián es una capa de defensa, **no la única**. La primera es que el usuario de conexión no pueda escribir. Ejemplos:

**PostgreSQL**

```sql
CREATE ROLE chatiapp_ro LOGIN PASSWORD '<contraseña>';
GRANT CONNECT ON DATABASE ventas TO chatiapp_ro;
GRANT USAGE ON SCHEMA public TO chatiapp_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO chatiapp_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO chatiapp_ro;
ALTER ROLE chatiapp_ro SET default_transaction_read_only = on;
ALTER ROLE chatiapp_ro SET statement_timeout = '30s';
```

**MySQL / MariaDB**

```sql
CREATE USER 'chatiapp_ro'@'%' IDENTIFIED BY '<contraseña>';
GRANT SELECT ON ventas.* TO 'chatiapp_ro'@'%';
```

**SQL Server**

```sql
CREATE LOGIN chatiapp_ro WITH PASSWORD = '<contraseña>';
USE ventas;
CREATE USER chatiapp_ro FOR LOGIN chatiapp_ro;
ALTER ROLE db_datareader ADD MEMBER chatiapp_ro;
```

Recomendaciones:

- Conecta a una **réplica de lectura** si existe: las consultas analíticas no compiten con la operación.
- Otorga `SELECT` solo sobre las tablas (o vistas) del modelo semántico, no sobre todo el esquema.
- Para datos muy sensibles, expón **vistas** que ya excluyan columnas personales y modela las vistas.

## Ejecución

- Transacción de solo lectura donde el motor lo permite (`SET TRANSACTION READ ONLY` en PostgreSQL y MySQL).
- Tiempo máximo por consulta (`timeout_seconds` de la fuente) y tope de filas (`max_rows`); si el resultado se recorta, la interfaz lo dice.
- Un *pool* de conexiones por fuente, con verificación previa (`pool_pre_ping`).
- Los valores se serializan a JSON con tipos estables: decimales como texto exacto, fechas en ISO 8601.
- Una fuente con `execute: false` funciona en **modo solo SQL**: genera y valida la consulta, pero no la ejecuta. Útil para empezar sin dar acceso a la base.
