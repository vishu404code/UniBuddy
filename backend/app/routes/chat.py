from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.ai.gemini_client import GeminiClient
from app.config import settings
from app.middleware.auth import CurrentSession, session_with_roles
from app.schemas.chat import (
    AskRequest,
    AskResponse,
    CitationOut,
    ConversationOut,
    ForwardRequest,
    ForwardResponse,
    MessageOut,
)
from app.schemas.common import Page
from app.services.chat import ask_question, forward_message_to_faculty
from app.services.providers import get_ai_client, get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/chat", tags=["chat"])
STUDENT_ONLY = ("student",)


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: SupabaseClient = Depends(get_supabase_client),
    ai: GeminiClient = Depends(get_ai_client),
):
    result = await ask_question(
        sb=sb,
        ai=ai,
        user=session.user,
        access_token=session.access_token,
        question=body.question,
        conversation_id=body.conversation_id,
        top_k=settings.retrieval_top_k,
        min_similarity=settings.retrieval_min_similarity,
    )
    answer = result.answer
    return AskResponse(
        conversation_id=result.conversation_id,
        user_message_id=result.user_message_id,
        assistant_message_id=result.assistant_message_id,
        answer=answer.text,
        abstained=answer.abstained,
        citations=[CitationOut(document_id=c.document_id, title=c.title, page=c.page) for c in answer.citations],
        escalation_available=answer.abstained,
    )


@router.get("/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    sb: SupabaseClient = Depends(get_supabase_client),
):
    rows, total = await sb.select_page_as_user(
        session.access_token,
        "conversations",
        {"select": "id,title,created_at", "order": "created_at.desc"},
        limit,
        offset,
    )
    return Page[ConversationOut](items=rows, total=total, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    conversation_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sb: SupabaseClient = Depends(get_supabase_client),
):
    rows, total = await sb.select_page_as_user(
        session.access_token,
        "messages",
        {
            "select": "id,role,content,citations,created_at",
            "conversation_id": f"eq.{conversation_id}",
            "order": "created_at.asc",
        },
        limit,
        offset,
    )
    return Page[MessageOut](items=rows, total=total, limit=limit, offset=offset)


@router.post("/messages/{message_id}/forward", response_model=ForwardResponse, status_code=201)
async def forward(
    message_id: UUID,
    body: ForwardRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    ticket = await forward_message_to_faculty(
        sb=sb,
        user=session.user,
        message_id=message_id,
        department_id=body.department_id,
        priority=body.priority,
        description=body.description,
    )
    return ForwardResponse(ticket_id=ticket["id"], ticket_number=ticket["ticket_number"], status=ticket["status"])
