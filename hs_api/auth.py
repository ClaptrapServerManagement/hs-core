import hashlib
import secrets
from dataclasses import dataclass

import asyncpg
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .db import get_conn
from .errors import ApiError

AGENT_KINDS = {"power_controller", "host_agent", "vm_agent", "service_manager"}

_bearer = HTTPBearer(auth_error=False)

def generate_token() -> str:
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

@dataclass
class Caller:
    id: int
    kind: str
    name: str

async def get_caller(
        credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
        conn: asyncpg.Connection = Depends(get_conn)
) -> Caller:
    if credentials is None:
        raise ApiError(401, "unauthorized", "Bearer-Token fehlt.")
    row = await conn.fetchrow(
        "SELECT id, kind::text AS kind, name FROM components WHERE api_token_hash = $1",
        hash_token(credentials.credentials),
    )
    if row is None:
        raise ApiError(401, "unauthorized", "Unbekanntes Token.")
    return Caller(**dict(row))

async def require_agent(caller: Caller = Depends(get_caller)) -> Caller:
    if caller.kind not in AGENT_KINDS:
        raise ApiError(403, "forbidden", f"Komponente '{caller.name}' darf das nicht.")