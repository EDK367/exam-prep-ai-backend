# app/main.py
from fastapi import FastAPI
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging
from app.core.middleware import register_middleware
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    # Startup actions
    yield
    # Shutdown actions


app = FastAPI(
    title="Exam Prep AI API",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

register_middleware(app)
app.include_router(api_router)


@app.get("/")
async def root():
    return {"message": "Exam Prep AI API is running", "version": settings.APP_VERSION}
