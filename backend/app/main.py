import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
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
        ai = get_ai_client() if settings.gemini_api_key else None
        worker_task = asyncio.create_task(run_forever(get_data_client(), ai))
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
@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "app": settings.app_name,
        "env": settings.app_env,
        "database_configured": bool(settings.database_url),
        "ai_configured": bool(settings.gemini_api_key),
        "r2_configured": bool(
            settings.r2_account_id
            and settings.r2_access_key_id
            and settings.r2_secret_access_key
        ),
        "google_auth_configured": bool(settings.google_client_id),
    }


@app.get(f"{settings.api_v1_prefix}/health/services")
async def health_services():
    """Separately tests connectivity to Database, AI, Storage and Auth."""
    results = {
        "database": {"status": "unconfigured", "details": None},
        "gemini_ai": {"status": "unconfigured", "details": None},
        "object_storage": {"status": "unconfigured", "details": None},
        "google_auth": {"status": "unconfigured", "details": None},
    }
    all_ok = True

    # 1. Database
    if settings.database_url:
        try:
            client = get_data_client()
            await client.select_service("campuses", {"limit": "1"})
            results["database"] = {"status": "connected", "details": "Neon PostgreSQL OK"}
        except Exception as exc:
            all_ok = False
            results["database"] = {"status": "error", "details": str(exc)}
    else:
        results["database"] = {
            "status": "unconfigured",
            "details": "DATABASE_URL not set in backend/.env",
        }

    # 2. Gemini AI
    if settings.gemini_api_key:
        results["gemini_ai"] = {
            "status": "configured",
            "chat_model": settings.gemini_chat_model,
            "embedding_model": settings.gemini_embedding_model,
        }
    else:
        results["gemini_ai"] = {
            "status": "unconfigured",
            "details": "GEMINI_API_KEY not set in backend/.env",
        }

    # 3. Object Storage
    if (
        settings.r2_account_id
        and settings.r2_access_key_id
        and settings.r2_secret_access_key
    ):
        results["object_storage"] = {
            "status": "configured",
            "bucket": settings.r2_bucket,
        }
    else:
        results["object_storage"] = {
            "status": "unconfigured",
            "details": "R2_ACCOUNT_ID or R2 credentials not set in backend/.env",
        }

    # 4. Google Auth
    if settings.google_client_id:
        results["google_auth"] = {
            "status": "configured",
            "client_id": settings.google_client_id[:16] + "...",
        }
    else:
        results["google_auth"] = {
            "status": "unconfigured",
            "details": "GOOGLE_CLIENT_ID not set in backend/.env",
        }

    status_code = 200 if (settings.database_url and all_ok) else 200
    return JSONResponse(status_code=status_code, content={"ready": all_ok, "services": results})


@app.post(f"{settings.api_v1_prefix}/health/diagnose-gemini")
async def diagnose_gemini_endpoint():
    """Diagnostic endpoint to test live Gemini API connection without exposing secrets."""
    if not settings.gemini_api_key:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unconfigured",
                "message": "GEMINI_API_KEY is not configured in backend/.env",
            },
        )
    ai = get_ai_client()
    diag = await ai.test_connection()
    status_code = 200 if diag.get("status") == "connected" else 502
    return JSONResponse(status_code=status_code, content=diag)


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
