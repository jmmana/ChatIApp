"""Importador del diccionario de datos (CSV o XLSX), docs/MODELO_SEMANTICO.md.

Una fila por columna; una fila con `columna` vacía describe la tabla. Las filas inválidas no
detienen la importación: se reportan con su número de fila (la fila 1 es el encabezado) y las
válidas se importan.
"""

import csv
import importlib
import io
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast, get_args

from app.semantic.schema import Column, ColumnRole, Table

_HEADERS = {
    "tabla": "table",
    "table": "table",
    "columna": "column",
    "column": "column",
    "tipo": "type",
    "type": "type",
    "descripcion": "description",
    "description": "description",
    "sinonimos": "synonyms",
    "synonyms": "synonyms",
    "rol": "role",
    "role": "role",
    "oculta": "hidden",
    "hidden": "hidden",
    "valores_ejemplo": "sample_values",
    "sample_values": "sample_values",
}
_TRUE = {"si", "true", "1"}
_FALSE = {"no", "false", "0"}
_ROLES = set(get_args(ColumnRole))
_SHEET_NAMES = {"diccionario", "dictionary"}


class DictionaryError(ValueError):
    """El archivo no se puede leer como diccionario (formato o encabezados inválidos)."""


@dataclass(frozen=True)
class RowIssue:
    """Una fila rechazada: `row` es el número de fila del archivo (el encabezado es la 1)."""

    row: int
    message: str

    def __str__(self) -> str:
        return f"fila {self.row}: {self.message}"


@dataclass
class DictionaryResult:
    tables: list[Table] = field(default_factory=list)
    issues: list[RowIssue] = field(default_factory=list)


def _normalize(text: str) -> str:
    """Minúsculas, sin tildes y con guion bajo en vez de espacios, para comparar."""
    decomposed = unicodedata.normalize("NFKD", text.strip().lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).replace(" ", "_")


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]


def _map_headers(header: Iterable[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, name in enumerate(header):
        key = _HEADERS.get(_normalize(name))
        if key is not None and key not in mapping:
            mapping[key] = index
    if "table" not in mapping:
        raise DictionaryError("Falta el encabezado obligatorio «tabla» (o «table»)")
    return mapping


def _parse_rows(rows: Iterable[list[str]]) -> DictionaryResult:
    iterator = iter(rows)
    header = next(iterator, None)
    if header is None:
        raise DictionaryError("El archivo está vacío")
    mapping = _map_headers(header)
    result = DictionaryResult()
    tables: dict[str, Table] = {}
    described: set[str] = set()

    def cell(row: list[str], key: str) -> str:
        index = mapping.get(key)
        return row[index].strip() if index is not None and index < len(row) else ""

    def reject(number: int, message: str) -> None:
        result.issues.append(RowIssue(number, message))

    for number, row in enumerate(iterator, start=2):
        if not any(value.strip() for value in row):
            continue
        table_name = cell(row, "table")
        if not table_name:
            reject(number, "La tabla es obligatoria")
            continue
        role = _normalize(cell(row, "role")) or "other"
        if role not in _ROLES:
            allowed = ", ".join(sorted(_ROLES))
            reject(number, f"Rol «{cell(row, 'role')}» no válido ({allowed})")
            continue
        raw_hidden = _normalize(cell(row, "hidden"))
        if raw_hidden and raw_hidden not in _TRUE | _FALSE:
            reject(number, f"Valor de oculta «{cell(row, 'hidden')}» no válido (si, no, 1, 0)")
            continue

        column_name = cell(row, "column")
        table = tables.get(table_name)
        if column_name and table and any(c.name == column_name for c in table.columns):
            reject(number, f"La columna «{column_name}» está repetida en «{table_name}»")
            continue
        if not column_name and table_name in described:
            reject(number, f"La tabla «{table_name}» está descrita dos veces")
            continue
        if table is None:
            table = tables[table_name] = Table(name=table_name)
            result.tables.append(table)
        if not column_name:
            described.add(table_name)
            table.description = cell(row, "description") or None
            table.synonyms = _split(cell(row, "synonyms"))
            continue
        table.columns.append(
            Column(
                name=column_name,
                type=cell(row, "type") or None,
                description=cell(row, "description") or None,
                synonyms=_split(cell(row, "synonyms")),
                role=cast(ColumnRole, role),
                hidden=raw_hidden in _TRUE,
                sample_values=list(_split(cell(row, "sample_values"))),
            )
        )
    return result


def parse_dictionary_csv(text: str) -> DictionaryResult:
    """Lee un diccionario CSV (coma, punto y coma o tabulador)."""
    text = text.removeprefix("﻿")
    first_line = text.splitlines()[0] if text.strip() else ""
    delimiter = max(",;\t", key=first_line.count)
    return _parse_rows(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter))


def _xlsx_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def parse_dictionary_xlsx(content: bytes) -> DictionaryResult:
    """Lee un diccionario XLSX: hoja `diccionario` o `dictionary`, o la primera."""
    openpyxl = importlib.import_module("openpyxl")
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise DictionaryError(f"No se pudo leer el XLSX: {exc}") from exc
    try:
        sheets = workbook.worksheets
        if not sheets:
            raise DictionaryError("El libro no tiene hojas")
        sheet = next((s for s in sheets if _normalize(s.title) in _SHEET_NAMES), sheets[0])
        rows = ([_xlsx_cell(v) for v in row] for row in sheet.iter_rows(values_only=True))
        return _parse_rows(rows)
    finally:
        workbook.close()


def import_dictionary(path: Path) -> DictionaryResult:
    """Lee un diccionario según la extensión: `.csv` o `.xlsx`."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return parse_dictionary_csv(path.read_text(encoding="utf-8"))
    if suffix == ".xlsx":
        return parse_dictionary_xlsx(path.read_bytes())
    raise DictionaryError(f"Formato «{suffix}» no soportado: usa .csv o .xlsx")
