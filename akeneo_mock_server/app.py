import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
import psycopg

from akeneo_mock_server.common import PatchTypeError
from akeneo_mock_server.database import close_db_pool
from akeneo_mock_server.routers.event_platform import router as event_platform_router
from akeneo_mock_server.routers.oauth import router as oauth_router
from akeneo_mock_server.routers.rest import router as rest_router
from akeneo_mock_server.routers.root import router as root_router


@asynccontextmanager
async def app_lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    close_db_pool()


def _build_internal_error_details(exc: Exception) -> dict[str, Any]:
    details: dict[str, Any] = {
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
    }
    if isinstance(exc, psycopg.Error):
        details["sqlstate"] = exc.sqlstate
        details["pg_error"] = str(exc)
        diag = exc.diag
        if diag is not None:
            details["pg_message_primary"] = diag.message_primary
            details["pg_message_detail"] = diag.message_detail
            details["pg_context"] = diag.context
            details["pg_schema_name"] = diag.schema_name
            details["pg_table_name"] = diag.table_name
            details["pg_column_name"] = diag.column_name
    return details


def create_app() -> FastAPI:
    app = FastAPI(title="Mock Akeneo API", lifespan=app_lifespan)

    @app.middleware("http")
    async def body_cache_middleware(request: Request, call_next):
        await request.body()
        try:
            return await call_next(request)
        except psycopg.errors.DataError as exc:
            logging.error("Unhandled error escaped middleware: %s: %s", type(exc).__name__, exc)
            return JSONResponse(
                status_code=422,
                content={
                    "code": 422,
                    "message": "Unprocessable Entity",
                    "details": _build_internal_error_details(exc),
                },
            )

    @app.exception_handler(PatchTypeError)
    async def patch_type_error_handler(request: Request, exc: PatchTypeError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"code": 422, "message": "Validation Error", "details": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.error("Internal Error intercepted: %s: %s", type(exc).__name__, exc)
        return JSONResponse(
            status_code=500,
            content={"code": 500, "message": "Internal Server Error", "details": _build_internal_error_details(exc)},
        )

    app.include_router(root_router)
    app.include_router(rest_router)
    app.include_router(oauth_router)
    app.include_router(event_platform_router)
    return app


app = create_app()
