
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth_routes import router as auth_router
from app.api.user_routes import router as user_router
from app.api.dashboard_routes import router as dashboard_router

from app.api.knowledge_source_routes import router as knowledge_source_router
from app.api.research_routes import router as research_router
from app.api.admin_ingestion_routes import router as admin_ingestion_router
from app.api.health_routes import router as health_router
from app.core.request_id import RequestIdMiddleware

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