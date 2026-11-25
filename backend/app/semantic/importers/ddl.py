"""Importador de DDL: convierte un script SQL en tablas, columnas, llaves y descripciones.

Lee `CREATE TABLE` (tipos, `PRIMARY KEY`, `REFERENCES` en línea, `FOREIGN KEY`, `UNIQUE`),
`COMMENT ON TABLE/COLUMN` (PostgreSQL, Oracle) y `COMMENT '…'` en línea (MySQL). Lo que no es
DDL de tablas se ignora y se reporta como advertencia: importar nunca falla por una sentencia.
`UNIQUE` se acepta pero no se guarda: el modelo semántico no tiene dónde representarlo.
"""

from dataclasses import dataclass, field

from sqlglot import Token, TokenType, exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import SqlglotError

from app.semantic.schema import Column, Issue, Relationship, Table

_PREVIEW = 60

# (columnas de origen, referencia) pendientes de resolver en una tabla
_Pending = list[tuple[list[str], exp.Reference]]
# (dónde, tabla origen, columna origen, tabla destino, columna destino)
_ForeignKey = tuple[str, str, str, str, str]


@dataclass
class DdlImport:
    """Resultado de importar un DDL: la estructura leída y lo que se ignoró."""

    tables: list[Table] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)


def import_ddl(sql: str, dialect: str | None = None) -> DdlImport:
    """Importa un script DDL escrito en `dialect` (por defecto, SQL genérico)."""
    result = DdlImport()
    reader = Dialect.get_or_raise(dialect)
    try:
        tokens = reader.tokenize(sql)
    except SqlglotError as exc:
        result.warnings.append(Issue("", f"No se pudo leer el script: {exc}"))
        return result

    tables: dict[str, Table] = {}  # por nombre en minúsculas
    comments: list[tuple[str, str, exp.Comment]] = []  # dónde, vista previa, sentencia
    foreign_keys: list[_ForeignKey] = []

    for chunk in _split(tokens):
        where = f"línea {chunk[0].line}"
        preview = " ".join(sql[chunk[0].start : chunk[-1].end + 1].split())[:_PREVIEW]
        try:
            statements = reader.parser().parse(chunk, sql)
        except SqlglotError:
            result.warnings.append(Issue(where, f"Sentencia ignorada, no se pudo leer: {preview}"))
            continue
        for statement in statements:
            if isinstance(statement, exp.Create) and _is_table(statement):
                table = _read_table(statement, reader, where, foreign_keys, result)
                if table is None:
                    continue
                if table.name.casefold() in tables:
                    result.warnings.append(Issue(where, f"Tabla repetida, se ignora: {table.name}"))
                else:
                    tables[table.name.casefold()] = table
                    result.tables.append(table)
            elif isinstance(statement, exp.Comment):
                comments.append((where, preview, statement))
            elif statement is not None:
                result.warnings.append(
                    Issue(where, f"Sentencia ignorada, no es DDL de tabla: {preview}")
                )

    for where, preview, comment in comments:
        _apply_comment(comment, tables, where, preview, result)
    _link(foreign_keys, tables, result)
    return result


def _split(tokens: list[Token]) -> list[list[Token]]:
    """Separa los tokens en sentencias por `;`, para que un error no afecte a las demás."""
    chunks: list[list[Token]] = []
    current: list[Token] = []
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            if current:
                chunks.append(current)
            current = []
        else:
            current.append(token)
    if current:
        chunks.append(current)
    return chunks


def _is_table(statement: exp.Create) -> bool:
    return str(statement.args.get("kind") or "").upper() == "TABLE"


def _table_name(table: exp.Table) -> str:
    return f"{table.db}.{table.name}" if table.db else table.name


def _names(nodes: list[exp.Expression]) -> list[str]:
    """Nombres de columna de una lista de identificadores, columnas o `Ordered`."""
    names: list[str] = []
    for node in nodes:
        ident = node if isinstance(node, exp.Identifier) else node.find(exp.Identifier)
        if ident is not None:
            names.append(ident.name)
    return names


def _reference(ref: exp.Reference) -> tuple[str, list[str]] | None:
    """Tabla y columnas destino de un `REFERENCES tabla (col, …)`."""
    target = ref.this
    columns = list(ref.args.get("expressions") or [])
    if isinstance(target, exp.Schema):
        columns = list(target.expressions)
        target = target.this
    if not isinstance(target, exp.Table):
        return None
    return _table_name(target), _names(columns)


def _text(node: object) -> str | None:
    text = node.name if isinstance(node, exp.Expression) else None
    return text or None


def _read_table(
    statement: exp.Create,
    reader: Dialect,
    where: str,
    foreign_keys: list[_ForeignKey],
    result: DdlImport,
) -> Table | None:
    schema = statement.this
    if not isinstance(schema, exp.Schema) or not isinstance(schema.this, exp.Table):
        result.warnings.append(Issue(where, "Sentencia ignorada: CREATE TABLE sin columnas"))
        return None
    name = _table_name(schema.this)
    table = Table(name=name)
    pending: _Pending = []

    for item in schema.expressions:
        if isinstance(item, exp.ColumnDef):
            _read_column(item, table, reader, pending)
        else:
            _read_constraint(item, table, pending)

    properties = statement.args.get("properties")
    if properties is not None:
        comment = properties.find(exp.SchemaCommentProperty)
        if comment is not None:
            table.description = _text(comment.this)

    for columns, ref in pending:
        target = _reference(ref)
        if target is None or not target[1] or len(target[1]) != len(columns):
            result.warnings.append(Issue(where, f"Llave foránea ilegible en {name}"))
            continue
        for column, ref_column in zip(columns, target[1], strict=True):
            foreign_keys.append((where, name, column, target[0], ref_column))
    return table


def _read_column(item: exp.ColumnDef, table: Table, reader: Dialect, pending: _Pending) -> None:
    name = item.name
    kind = item.args.get("kind")
    column = Column(name=name, type=kind.sql(dialect=reader).lower() if kind else None)
    for constraint in item.args.get("constraints") or []:
        spec = constraint.args.get("kind")
        if isinstance(spec, exp.PrimaryKeyColumnConstraint):
            table.primary_key.append(name)
        elif isinstance(spec, exp.Reference):
            pending.append(([name], spec))
        elif isinstance(spec, exp.CommentColumnConstraint):
            column.description = _text(spec.this)
        # UNIQUE, NOT NULL, DEFAULT, etc. no tienen lugar en el modelo semántico
    table.columns.append(column)


def _read_constraint(item: exp.Expression, table: Table, pending: _Pending) -> None:
    if isinstance(item, exp.Constraint):  # CONSTRAINT nombre <restricción>
        for inner in item.expressions:
            _read_constraint(inner, table, pending)
    elif isinstance(item, exp.PrimaryKey):
        table.primary_key.extend(_names(list(item.expressions)))
    elif isinstance(item, exp.ForeignKey):
        ref = item.args.get("reference")
        if isinstance(ref, exp.Reference):
            pending.append((_names(list(item.expressions)), ref))


def _apply_comment(
    statement: exp.Comment, tables: dict[str, Table], where: str, preview: str, result: DdlImport
) -> None:
    target = statement.this
    text = _text(statement.expression)
    if text is None:
        return
    if isinstance(target, exp.Column):
        table_name = f"{target.db}.{target.table}" if target.db else target.table
        table = tables.get(table_name.casefold())
        column = None
        if table is not None:
            column = next(
                (c for c in table.columns if c.name.casefold() == target.name.casefold()), None
            )
        if column is None:
            result.warnings.append(Issue(where, f"COMMENT sobre columna desconocida: {preview}"))
        else:
            column.description = text
    elif isinstance(target, exp.Table):
        found = tables.get(_table_name(target).casefold())
        if found is None:
            result.warnings.append(Issue(where, f"COMMENT sobre tabla desconocida: {preview}"))
        else:
            found.description = text
    else:
        result.warnings.append(Issue(where, f"COMMENT no soportado, se ignora: {preview}"))


def _link(foreign_keys: list[_ForeignKey], tables: dict[str, Table], result: DdlImport) -> None:
    """Convierte las llaves foráneas en relaciones, ya conocidas todas las tablas."""
    seen: set[tuple[str, str]] = set()
    for where, table, column, ref_table, ref_column in foreign_keys:
        target = tables.get(ref_table.casefold())
        if target is None:
            result.warnings.append(
                Issue(where, f"Llave foránea hacia una tabla fuera del script: {ref_table}")
            )
            continue
        pair = (f"{table}.{column}", f"{target.name}.{ref_column}")
        if pair not in seen:
            seen.add(pair)
            result.relationships.append(Relationship(from_=pair[0], to=pair[1]))
