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

Si coinciden, la tabla derivada no agrega operadores (ni `Subquery Scan` ni `Table Spool`): el optimizador empujó el filtro hacia la tabla. Cada ejecución del job de integración (`.github/workflows/integration.yml`) sube lo capturado como artefacto (`planes-de-ejecucion`).

**Resultado (27 de noviembre de 2026, corrida verde de Integración sobre `main`):**

| Caso | PostgreSQL 16 | SQL Server 2022 |
|---|---|---|
| `facturas` (conteo) | Mismos operadores con la tabla derivada y con el `WHERE` escrito a mano: `Aggregate` → `Seq Scan on facturas` con `Filter: sucursal_id = ANY ('{1,2}')` y el filtro de estado. | La prueba pasa: lista de operadores idéntica en ambas variantes. |
| `join` con `sucursales` | `HashAggregate` → `Hash Join` → `Seq Scan on facturas` (con el filtro de sucursal) y `Hash` → `Seq Scan on sucursales`; misma forma en ambas. Solo cambia el calificador de la condición del `Hash Join` (`facturas.sucursal_id` frente a `f.sucursal_id`), que la prueba ignora a propósito. | La prueba pasa: lista de operadores idéntica. |
| `resumida` (`ventas_diarias`) | Mismos operadores en ambas variantes. | La prueba pasa: lista de operadores idéntica. |

- **PostgreSQL:** el filtro llega hasta el recorrido de la tabla; no aparece `Subquery Scan` y la tabla derivada **no agrega operadores**. No se registró el costo porque el plan se pide con `COSTS OFF`.
- **SQL Server:** lo comprobado es la aserción de la prueba (operadores idénticos y predicado `sucursal_id` presente, con `SET SHOWPLAN_TEXT ON`). **El artefacto solo guarda el texto de las consultas, no el plan de SQL Server**, así que el plan completo no queda archivado. Si se quiere dejar evidencia, la prueba debe escribir también el `SHOWPLAN_TEXT`.
- Ningún caso mostró un operador extra (ni `Subquery Scan` ni `Table Spool`) en los dos motores.

## Alternativas consideradas

- **Agregar la condición al `WHERE` de cada `SELECT`.** Hay que calificar columnas con el alias correcto en cada ámbito y no romper `OR` existentes; más frágil.
- **Seguridad a nivel de fila del motor (RLS de PostgreSQL, SQL Server).** Excelente donde existe, pero no en todos los motores y exige un usuario de base por usuario o contexto de sesión. Recomendada como capa adicional, no como única.
- **Vistas por rol.** Funcionan, pero multiplican objetos en la base del cliente.
