# ADR 0004 · El filtro por rol reemplaza la tabla por una tabla derivada

- **Estado:** aceptada
- **Fecha:** 2026-11-25

## Contexto

Un gerente de sucursal solo debe ver sus sucursales, haga la pregunta que haga. El filtro tiene que aplicarse a **cada** aparición de la tabla: en joins, subconsultas, CTE y uniones, con o sin alias, y tanto en el SQL del catálogo como en el de la IA.

## Decisión

Reemplazar cada referencia a una tabla filtrada por una **tabla derivada** con el filtro, conservando el alias original:

```sql
FROM facturas f
-- se convierte en
FROM (SELECT * FROM facturas WHERE sucursal_id IN (1, 2)) AS f
```

La condición viene del modelo semántico (`sucursal_id IN ({user.sucursales})`). Los valores salen del usuario autenticado y sqlglot los inserta como literales escapados. Si falta un atributo, la consulta se rechaza.

Se probó con sqlglot 30.35 en joins (`sqlite`), subconsultas en `WHERE` (`mysql`), CTE (`postgres`) y con `TOP` (`tsql`). Las salidas están en [SEGURIDAD.md](../SEGURIDAD.md#filtro-por-rol).

## Consecuencias

- ✅ No importa dónde aparezca la tabla ni qué alias tenga: la versión sin filtrar deja de existir para esa consulta.
- ✅ No hay que entender la lógica del `WHERE` original ni combinar condiciones con `AND`/`OR`, donde un error de paréntesis abriría un hueco.
- ⚠️ El SQL resultante es más largo. Los optimizadores de PostgreSQL, SQL Server, MySQL 8, Oracle, Snowflake y BigQuery empujan el filtro hacia la tabla, así que el costo es mínimo; se confirma con planes de ejecución en las pruebas de integración multimotor ([revisión](#revisión-de-planes-de-ejecución)).
- ⚠️ Si una tabla aparece en una resumida sin filtro configurado, el rol podría ver más de lo debido por esa vía. El validador del modelo avisa cuando una tabla filtrada tiene resumidas sin filtro.

## Revisión de planes de ejecución

`backend/tests/integration/test_planes.py` compara, en PostgreSQL 16 y SQL Server 2022, el plan de la consulta con la tabla derivada contra el de la misma consulta con el filtro escrito a mano en el `WHERE`. Casos: `facturas` (conteo), `join` con `sucursales` y `resumida` (`ventas_diarias`). La prueba exige que:

- el predicado `sucursal_id` aparezca en el plan (el filtro no se pierde), y
- la lista de operadores sea idéntica en ambas variantes, sin costos ni objetos: PostgreSQL con `EXPLAIN (COSTS OFF)` y SQL Server con `SET SHOWPLAN_TEXT ON`.

Si coinciden, la tabla derivada no agrega operadores (ni `Subquery Scan` ni `Table Spool`): el optimizador empujó el filtro hacia la tabla. Cada ejecución del job `integration` sube los planes completos como artefacto (`planes-integracion`).

**Resultado:** pendiente de registrar. La revisión solo se puede ejecutar contra los motores reales del CI; al correr el job por primera vez, quien revisa debe anotar aquí el resultado de cada caso (y, si algún plan difiere, el operador extra y su costo) antes de dar por cerrado el criterio.

## Alternativas consideradas

- **Agregar la condición al `WHERE` de cada `SELECT`.** Hay que calificar columnas con el alias correcto en cada ámbito y no romper `OR` existentes; más frágil.
- **Seguridad a nivel de fila del motor (RLS de PostgreSQL, SQL Server).** Excelente donde existe, pero no en todos los motores y exige un usuario de base por usuario o contexto de sesión. Recomendada como capa adicional, no como única.
- **Vistas por rol.** Funcionan, pero multiplican objetos en la base del cliente.
