
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.auth_routes import router as auth_router
from app.api.user_routes import router as user_router
from app.api.dashboard_routes import router as dashboard_router

from app.api.knowledge_source_routes import router as knowledge_source_router
from app.api.research_routes import router as research_router
from app.api.admin_ingestion_routes import router as admin_ingestion_router
from app.api.health_routes import router as health_router
from app.api.assistant_routes import router as assistant_router
from app.core.request_id import HEADER as REQUEST_ID_HEADER, RequestIdMiddleware, request_id_of
from app.api.draft_routes import router as draft_router
from app.api.matter_routes import router as matter_router
from app.api.citation_routes import router as citation_router
from app.api.judge_support_routes import router as judge_support_router
from app.api.admin_evaluation_routes import router as admin_evaluation_router
from app.safety.redaction import install_log_redaction, redact_secrets

logger = logging.getLogger("app.errors")
install_log_redaction()

INTERNAL_ERROR_MESSAGE = (
    "Something went wrong on our side and your request could not be completed. "
    "Please try again. If the problem continues, contact the administrator "
    "with the request ID."
)

app = FastAPI(
    title="LawPilot AI",
    description="Multi-Agent AI Legal Support System",
    version="1.0.0"
)

# Adds an X-Request-ID to every request/response (stored in audit_events).
app.add_middleware(RequestIdMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):517[0-9]+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# SCRUM-27: safe error responses. Users get a short, understandable message
# and the request ID; stack traces stay in the (secret-redacted) server log,
# and submitted values (e.g. a password) are never echoed back.
# --------------------------------------------------------------------------- #
def _with_request_id(request: Request, response: JSONResponse) -> JSONResponse:
    request_id = request_id_of(request)
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", "Invalid value."), "type": e.get("type", "value_error")}
        for e in exc.errors()
    ]
    return _with_request_id(request, JSONResponse(status_code=422, content={"detail": errors}))


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    if isinstance(detail, str):
        detail = redact_secrets(detail)
    return _with_request_id(
        request,
        JSONResponse(status_code=exc.status_code, content={"detail": detail}, headers=getattr(exc, "headers", None)),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    request_id = request_id_of(request)
    logger.exception("Unhandled error request_id=%s path=%s", request_id, request.url.path)
    return _with_request_id(
        request,
        JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_MESSAGE, "request_id": request_id}),
    )


@app.get("/")
def root():
    return {"message": "LawPilot AI Backend is running"}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


# Register authentication endpoints
app.include_router(auth_router)
app.include_router(user_router)
app.include_router(dashboard_router)
app.include_router(knowledge_source_router)
app.include_router(research_router)
app.include_router(admin_ingestion_router)
app.include_router(health_router)
app.include_router(assistant_router)
app.include_router(draft_router)
app.include_router(matter_router)
app.include_router(citation_router)
app.include_router(judge_support_router)
app.include_router(admin_evaluation_router)
