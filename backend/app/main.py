from fastapi import APIRouter, FastAPI

from app.api import health

# Every backend route lives under /api (the frontend rewrites /api/* here).
api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)

app = FastAPI(title="UH-NI-ME API")
app.include_router(api_router)
