"""Línea de comandos de ChatIApp: `chatiapp keys create|list|revoke` (docs/INTEGRACION.md).

Usa las mismas opciones y las mismas reglas que la API de administración, directamente sobre la
base de la app (`CHATIAPP_DATABASE_URL`).
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session, sessionmaker

from app.db.models import ApiKey
from app.db.session import get_engine
from app.integrations import api_keys as service
from app.security.auth import AuthError

SessionFactory = Callable[[], Session]


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"fecha ISO 8601 inválida: {value}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"número inválido: {value}") from exc


def _extend(values: list[list[str]] | None) -> list[str]:
    return [item for group in values or [] for item in group]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="chatiapp", description="Administración de ChatIApp")
    commands = parser.add_subparsers(dest="command", required=True)
    keys_parser = commands.add_parser("keys", help="API keys de servidor")
    keys = keys_parser.add_subparsers(dest="action", required=True)

    create = keys.add_parser("create", help="Crea una key; el secreto se muestra una sola vez")
    create.add_argument("--name", required=True, help="Nombre descriptivo")
    create.add_argument(
        "--scopes",
        required=True,
        type=_csv,
        help=f"Alcances separados por coma: {', '.join(service.SCOPES)}",
    )
    create.add_argument(
        "--datasource", action="append", type=_csv, help="Fuente permitida (repetible o con comas)"
    )
    create.add_argument(
        "--roles", action="append", type=_csv, help="Rol permitido (repetible o con comas)"
    )
    create.add_argument(
        "--origin", action="append", type=_csv, help="Origen permitido (repetible o con comas)"
    )
    create.add_argument("--rate-limit", type=int, help="Peticiones por minuto")
    create.add_argument("--monthly-budget", type=_decimal, help="Presupuesto mensual en USD")
    create.add_argument("--expires-at", type=_datetime, help="Expiración ISO 8601 (UTC sin zona)")

    keys.add_parser("list", help="Lista las keys")

    revoke = keys.add_parser("revoke", help="Revoca una key al instante")
    revoke.add_argument("key", help="Id o prefijo visible (chia_<id>)")
    return parser


def _describe(api_key: ApiKey) -> str:
    expires_at = api_key.expires_at
    if api_key.revoked_at is not None:
        state = "revocada"
    elif expires_at is not None and service.as_utc(expires_at) <= datetime.now(UTC):
        state = "expirada"
    else:
        state = "activa"
    used = api_key.last_used_at.isoformat() if api_key.last_used_at else "nunca"
    return "\t".join(
        [
            str(api_key.id),
            api_key.prefix,
            state,
            api_key.name,
            ",".join(api_key.scopes),
            f"último uso: {used}",
        ]
    )


def _run(args: argparse.Namespace, session: Session) -> int:
    if args.action == "create":
        api_key, secret = service.create_api_key(
            session,
            name=args.name,
            scopes=args.scopes,
            datasources=_extend(args.datasource),
            allowed_roles=_extend(args.roles),
            allowed_origins=_extend(args.origin),
            rate_limit_per_minute=args.rate_limit,
            monthly_budget_usd=args.monthly_budget,
            expires_at=args.expires_at,
        )
        print(f"Key creada: {api_key.id} ({api_key.prefix}). Secreto, una sola vez:", file=sys.stderr)
        print(secret)
    elif args.action == "list":
        for api_key in service.list_api_keys(session):
            print(_describe(api_key))
    else:
        api_key = service.find_api_key(session, args.key)
        service.revoke_api_key(session, api_key.id)
        print(f"Key revocada: {api_key.id} ({api_key.prefix})", file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None, session_factory: SessionFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    factory = session_factory or sessionmaker(bind=get_engine(), expire_on_commit=False)
    try:
        with factory() as session:
            return _run(args, session)
    except (ValueError, AuthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
