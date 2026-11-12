
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth_routes import router as auth_router
from app.api.user_routes import router as user_router
from app.api.dashboard_routes import router as dashboard_router

from app.api.knowledge_source_routes import router as knowledge_source_router

app = FastAPI(
    title="LawPilot AI",
    description="Multi-Agent AI Legal Support System",
    version="1.0.0"
)

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