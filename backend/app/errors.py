import json
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger("mc_panel")


class Problem(Exception):
    def __init__(self, status: int, code: str, headers: dict[str, str] | None = None):
        self.status = status
        self.code = code
        self.headers = headers


def install_errors(app: FastAPI) -> None:
    def response(request: Request, status: int, code: str, headers=None) -> JSONResponse:
        return JSONResponse(
            {
                "type": "about:blank",
                "status": status,
                "title": code.replace("_", " ").title(),
                "code": code,
                "request_id": request.state.request_id,
            },
            status_code=status,
            headers=headers,
            media_type="application/problem+json",
        )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = uuid.uuid4().hex
        try:
            result = await call_next(request)
        except Exception:  # noqa: BLE001 - Never serialize exceptions containing request data.
            logger.error(
                json.dumps(
                    {
                        "event": "request_failed",
                        "request_id": request.state.request_id,
                    }
                )
            )
            result = response(request, 500, "INTERNAL_ERROR")
        result.headers["X-Request-ID"] = request.state.request_id
        result.headers["Cache-Control"] = "no-store"
        result.headers["X-Content-Type-Options"] = "nosniff"
        return result

    @app.exception_handler(Problem)
    async def problem(request: Request, exc: Problem):
        return response(request, exc.status, exc.code, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def validation(request: Request, exc: RequestValidationError):
        return response(request, 422, "INVALID_INPUT")

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        return response(request, exc.status_code, f"HTTP_{exc.status_code}", exc.headers)
