import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.gemini_client import AIServiceError
from app.config import settings
from app.routes.admin import router as admin_router
from app.routes.announcements import router as announcements_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.departments import router as departments_router
from app.routes.dashboards import router as dashboards_router
from app.routes.documents import router as documents_router
from app.routes.notifications import router as notifications_router
from app.routes.provisioning import router as provisioning_router
from app.routes.tickets import router as tickets_router
from app.services.document_worker import run_forever
from app.services.documents import DocumentError
from app.services.errors import DataServiceError
from app.services.providers import get_ai_client, get_data_client

logger = logging.getLogger("unibuddy")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker_task = None
    if settings.document_worker_enabled and settings.database_url and settings.session_secret:
        try:
            ai = get_ai_client() if settings.gemini_api_key else None
            worker_task = asyncio.create_task(run_forever(get_data_client(), ai))
            logger.info("Document worker started in this process")
        except HTTPException as exc:
            # Keep the API up (health checks, sign-in, read routes) when storage is not configured yet.
            # Uploads still fail with a clear 503 until the missing settings are added.
            logger.warning("Document worker not started: %s", exc.detail)
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(DocumentError)
async def document_error_handler(_request: Request, exc: DocumentError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


# Client-facing messages are generic. Database detail stays in the server log only.
_DATA_MESSAGES = {
    400: "The request could not be processed.",
    403: "You are not allowed to do that.",
    404: "Not found.",
    409: "This conflicts with existing data.",
    503: "The service is temporarily unavailable.",
}


@app.exception_handler(DataServiceError)
async def data_error_handler(_request: Request, exc: DataServiceError):
    logger.error("Data request failed with HTTP %s", exc.status_code)
    status_code = exc.status_code if exc.status_code in _DATA_MESSAGES else 502
    message = _DATA_MESSAGES.get(exc.status_code, "Database request failed.")
    return JSONResponse(status_code=status_code, content={"detail": message})


@app.exception_handler(AIServiceError)
async def ai_error_handler(_request: Request, exc: AIServiceError):
    logger.error("AI request failed: %s", exc)
    return JSONResponse(status_code=502, content={"detail": "AI service request failed"})


@app.get(f"{settings.api_v1_prefix}/health")
def health_check():
    return {"status": "ok", "app": settings.app_name, "env": settings.app_env}


for router in (
    auth_router,
    documents_router,
    chat_router,
    tickets_router,
    announcements_router,
    notifications_router,
    dashboards_router,
    provisioning_router,
    admin_router,
    departments_router,
):
    app.include_router(router, prefix=settings.api_v1_prefix)
