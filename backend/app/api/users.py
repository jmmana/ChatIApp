"""Administración de usuarios y de su rol por fuente (docs/API.md#administración-m3)."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.errors import ApiError
from app.db.models import Datasource, User
from app.db.session import get_session
from app.engine.rls import AttributeValue
from app.security.auth import get_current_user, hash_password, normalize_email
from app.security.grants import GrantError, replace_grants, validate_grant
from app.semantic import store

# El router se incluye con `require_admin` en `main.py`.
router = APIRouter(prefix="/users", tags=["usuarios"])

SessionDep = Annotated[Session, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]

Password = Annotated[str, Field(min_length=8, max_length=256)]


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    datasource_id: uuid.UUID
    role: str = Field(min_length=1)
    attributes: dict[str, AttributeValue] = {}


class GrantsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grants: list[GrantIn]


class GrantOut(BaseModel):
    datasource_id: uuid.UUID
    role: str
    attributes: dict[str, Any]


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: Password
    is_admin: bool = False


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = Field(default=None, min_length=3, max_length=320)
    password: Password | None = None
    is_admin: bool | None = None


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    is_admin: bool
    grants: list[GrantOut]


def _out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        grants=[
            GrantOut(datasource_id=g.datasource_id, role=g.role, attributes=dict(g.attributes))
            for g in sorted(user.grants, key=lambda g: str(g.datasource_id))
        ],
    )


def _get(session: Session, user_id: uuid.UUID) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise ApiError(404, "user_not_found", "El usuario no existe")
    return user


def _email(raw: str) -> str:
    email = normalize_email(raw)
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise ApiError(422, "invalid_email", "El correo no es válido")
    return email


def _email_taken(session: Session, email: str, except_id: uuid.UUID | None = None) -> bool:
    other = session.scalar(select(User).where(User.email == email))
    return other is not None and other.id != except_id


def _admin_count(session: Session) -> int:
    return len(session.scalars(select(User.id).where(User.is_admin.is_(True))).all())


@router.get("", summary="Lista los usuarios con sus permisos")
def list_users(session: SessionDep) -> list[UserOut]:
    users = session.scalars(select(User).order_by(User.email)).all()
    return [_out(u) for u in users]


@router.post("", status_code=201, summary="Crea un usuario")
def create_user(body: UserCreate, session: SessionDep) -> UserOut:
    email = _email(body.email)
    if _email_taken(session, email):
        raise ApiError(409, "email_taken", "Ya existe un usuario con ese correo")
    user = User(email=email, password_hash=hash_password(body.password), is_admin=body.is_admin)
    session.add(user)
    try:
        session.commit()
    except IntegrityError as exc:  # carrera con otra creación del mismo correo
        session.rollback()
        raise ApiError(409, "email_taken", "Ya existe un usuario con ese correo") from exc
    return _out(user)


@router.get("/{user_id}", summary="Un usuario con sus permisos")
def get_user(user_id: uuid.UUID, session: SessionDep) -> UserOut:
    return _out(_get(session, user_id))


@router.patch("/{user_id}", summary="Cambia correo, contraseña o rol de administrador")
def update_user(user_id: uuid.UUID, body: UserUpdate, session: SessionDep) -> UserOut:
    user = _get(session, user_id)
    if body.email is not None:
        email = _email(body.email)
        if _email_taken(session, email, user.id):
            raise ApiError(409, "email_taken", "Ya existe un usuario con ese correo")
        user.email = email
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.is_admin is not None and body.is_admin != user.is_admin:
        if not body.is_admin and _admin_count(session) <= 1:
            raise ApiError(409, "last_admin", "Debe quedar al menos un administrador")
        user.is_admin = body.is_admin
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise ApiError(409, "email_taken", "Ya existe un usuario con ese correo") from exc
    return _out(user)


@router.delete("/{user_id}", status_code=204, summary="Elimina un usuario y sus permisos")
def delete_user(user_id: uuid.UUID, session: SessionDep, current: CurrentUser) -> Response:
    user = _get(session, user_id)
    if user.id == current.id:
        raise ApiError(409, "self_delete", "No puedes eliminar tu propio usuario")
    if user.is_admin and _admin_count(session) <= 1:
        raise ApiError(409, "last_admin", "Debe quedar al menos un administrador")
    for grant in list(user.grants):
        session.delete(grant)
    session.delete(user)
    session.commit()
    return Response(status_code=204)


@router.put(
    "/{user_id}/grants",
    summary="Fija el rol y los atributos del usuario en cada fuente de datos",
)
def put_grants(user_id: uuid.UUID, body: GrantsIn, session: SessionDep) -> UserOut:
    """Reemplaza los permisos del usuario. Cada rol debe existir en el modelo vigente de su fuente
    y los atributos que exigen sus filtros deben venir (422 si no)."""
    user = _get(session, user_id)
    entries: dict[uuid.UUID, tuple[str, dict[str, Any]]] = {}
    for item in body.grants:
        if item.datasource_id in entries:
            raise ApiError(422, "duplicate_datasource", "Una fuente aparece más de una vez")
        if session.get(Datasource, item.datasource_id) is None:
            raise ApiError(404, "datasource_not_found", "La fuente de datos no existe")
        row = store.current(session, item.datasource_id)
        if row is None:
            raise ApiError(
                422, "semantic_model_not_found", "La fuente aún no tiene modelo semántico"
            )
        try:
            validate_grant(store.load_model(row), item.role, item.attributes)
        except GrantError as exc:
            raise ApiError(exc.status_code, exc.code, exc.message) from exc
        entries[item.datasource_id] = (item.role, dict(item.attributes))
    replace_grants(session, user.id, entries)
    session.commit()
    session.refresh(user)
    return _out(user)
