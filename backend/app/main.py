import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.openai_client import OpenAIError
from app.config import settings
from app.routes.admin import router as admin_router
from app.routes.announcements import router as announcements_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.dashboards import router as dashboards_router
from app.routes.documents import router as documents_router
from app.routes.notifications import router as notifications_router
from app.routes.provisioning import router as provisioning_router
from app.routes.tickets import router as tickets_router
from app.services.document_worker import run_forever
from app.services.documents import DocumentError
from app.services.providers import get_supabase_client
from app.services.supabase_client import SupabaseError
from app.worker import build_clients

logger = logging.getLogger("unibuddy")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker_task = None
    if settings.document_worker_enabled and settings.supabase_url and settings.supabase_secret_key:
        _sb, ai = build_clients()
        worker_task = asyncio.create_task(run_forever(get_supabase_client(), ai))
        logger.info("Document worker started in this process")
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


@app.exception_handler(SupabaseError)
async def supabase_error_handler(_request: Request, exc: SupabaseError):
    logger.error("Supabase request failed with HTTP %s", exc.status_code)
    return JSONResponse(status_code=502, content={"detail": "Database request failed"})


@app.exception_handler(OpenAIError)
async def openai_error_handler(_request: Request, exc: OpenAIError):
    logger.error("OpenAI request failed: %s", exc)
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
):
    app.include_router(router, prefix=settings.api_v1_prefix)
