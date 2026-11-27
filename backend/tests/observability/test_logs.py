import json
import logging
import sys
from collections.abc import Iterator

from app.observability.logs import JsonFormatter, LogScope, redact


def _record(message: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("prueba", logging.INFO, __file__, 1, message, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def _emit(record: logging.LogRecord) -> dict[str, object]:
    return json.loads(JsonFormatter().format(record))


def test_el_log_es_json_y_lleva_el_contexto_del_turno() -> None:
    scope = LogScope("conv-1", "usuario-7")
    scope.update(turn_id="turno-9", stage="guard")
    seen: list[dict[str, object]] = []

    def events() -> Iterator[int]:
        seen.append(_emit(_record("dentro")))
        yield 1

    for _ in scope.wrap(events()):
        seen.append(_emit(_record("fuera")))

    assert seen[0]["turn_id"] == "turno-9" and seen[0]["conversation_id"] == "conv-1"
    assert seen[0]["user"] == "usuario-7" and seen[0]["stage"] == "guard"
    assert seen[0]["message"] == "dentro"
    assert "turn_id" not in seen[1]  # el contexto no se filtra al consumidor


def test_solo_salen_campos_conocidos_y_sin_secretos() -> None:
    clave = "sk" + "-prueba-" + "abcdefgh1234"
    entry = _emit(
        _record(
            f"Fallo con api_key={clave} y Bearer abc.def",
            rows=[["dato", "privado"]],
            tokens_in=12,
            provider="fake",
        )
    )

    assert "rows" not in entry
    assert entry["tokens_in"] == 12 and entry["provider"] == "fake"
    assert clave not in json.dumps(entry) and "abc.def" not in json.dumps(entry)


def test_la_excepcion_no_incluye_su_mensaje() -> None:
    try:
        raise ValueError("fila secreta: Norte, 1234")
    except ValueError:
        record = _record("falló")
        record.exc_info = sys.exc_info()

    entry = _emit(record)

    assert entry["exc_type"] == "ValueError"
    assert "fila secreta" not in json.dumps(entry)


def test_redact_tapa_credenciales() -> None:
    assert "hunter2" not in redact("password: hunter2")
    assert redact("texto normal") == "texto normal"
