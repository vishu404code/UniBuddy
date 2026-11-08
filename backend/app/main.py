import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.ai.openai_client import OpenAIError
from app.config import settings
from app.routes.announcements import router as announcements_router
from app.routes.auth import router as auth_router
from app.routes.chat import router as chat_router
from app.routes.dashboards import router as dashboards_router
from app.routes.documents import router as documents_router
from app.routes.notifications import router as notifications_router
from app.routes.tickets import router as tickets_router
from app.services.documents import DocumentError
from app.services.supabase_client import SupabaseError

logger = logging.getLogger("unibuddy")

app = FastAPI(title=settings.app_name)

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
):
    app.include_router(router, prefix=settings.api_v1_prefix)
