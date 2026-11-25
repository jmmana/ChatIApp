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
- ⚠️ El SQL resultante es más largo. Los optimizadores de PostgreSQL, SQL Server, MySQL 8, Oracle, Snowflake y BigQuery empujan el filtro hacia la tabla, así que el costo es mínimo; se confirmará con planes de ejecución en las pruebas de integración multimotor.
- ⚠️ Si una tabla aparece en una resumida sin filtro configurado, el rol podría ver más de lo debido por esa vía. El validador del modelo avisa cuando una tabla filtrada tiene resumidas sin filtro.

## Alternativas consideradas

- **Agregar la condición al `WHERE` de cada `SELECT`.** Hay que calificar columnas con el alias correcto en cada ámbito y no romper `OR` existentes; más frágil.
- **Seguridad a nivel de fila del motor (RLS de PostgreSQL, SQL Server).** Excelente donde existe, pero no en todos los motores y exige un usuario de base por usuario o contexto de sesión. Recomendada como capa adicional, no como única.
- **Vistas por rol.** Funcionan, pero multiplican objetos en la base del cliente.
