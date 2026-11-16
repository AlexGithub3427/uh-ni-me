from fastapi import APIRouter, FastAPI

from app.api import health, play, puzzle

# Every backend route lives under /api (the frontend rewrites /api/* here).
api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(puzzle.router)
api_router.include_router(play.router)

app = FastAPI(title="UH-NI-ME API")
app.include_router(api_router)
