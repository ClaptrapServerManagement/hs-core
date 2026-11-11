import asyncpg
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}

def _response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    headers = {}
    if details and details.get("retry_after_seconds"):
        headers["Retry-After"] = str(details["retry_after_seconds"])
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body), headers=headers)

def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return _response(exec.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _response(422, "validation_failed", "Ungültige Anfrage.", {"errors": exc.errors()})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "not found" if exc.status_code == 404 else "http_error"
        return _response(exc.status_code, code, str(exc.detail))

    # Database errors
    @app.exception_handler(asyncpg.UniqueViolationError)
    async def _unique(request: Request, exc: asyncpg.UniqueViolationError) -> JSONResponse:
        return _response(409, "already_exists", "Ein Eintrag mit diesem Wert existiert bereits.",
                         {"constraint": exc.constraint_name})

    @app.exception_handler(asyncpg.ForeignKeyViolationError)
    async def _foreign_key(request: Request, exc: asyncpg.ForeignKeyViolationError) -> JSONResponse:
        return _response(409, "still_referenced",
                         "Der Eintrag wird noch verwendet oder verweist auf etwas, das es nicht gibt.",
                         {"constraint": exc.constraint_name})

    @app.exception_handler(asyncpg.CheckViolationError)
    async def _check(request: Request, exc: asyncpg.CheckViolationError) -> JSONResponse:
        return _response(422, "invalid_value", "Ein Wert verletzt eine Regel der Datenbank.",
                         {"constraint": exc.constraint_name})

    @app.exception_handler(asyncpg.DataError)
    async def _data(request: Request, exc: asyncpg.DataError) -> JSONResponse:
        return _response(422, "invalid_value", f"Ungültiger Wert: {exc}")

    @app.exception_handler(asyncpg.RaiseError)
    async def _raise(request: Request, exc: asyncpg.RaiseError) -> JSONResponse:
        return _response(422, "invalid_value", str(exc))