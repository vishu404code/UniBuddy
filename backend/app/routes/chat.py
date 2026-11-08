from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.ai.openai_client import OpenAIClient
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
from app.services.chat import ask_question, forward_message_to_faculty
from app.services.providers import get_openai_client, get_supabase_client
from app.services.supabase_client import SupabaseClient

router = APIRouter(prefix="/chat", tags=["chat"])
STUDENT_ONLY = ("student",)


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: SupabaseClient = Depends(get_supabase_client),
    ai: OpenAIClient = Depends(get_openai_client),
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


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await sb.select_as_user(
        session.access_token,
        "conversations",
        {"select": "id,title,created_at", "order": "created_at.desc"},
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def list_messages(
    conversation_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: SupabaseClient = Depends(get_supabase_client),
):
    return await sb.select_as_user(
        session.access_token,
        "messages",
        {
            "select": "id,role,content,citations,created_at",
            "conversation_id": f"eq.{conversation_id}",
            "order": "created_at.asc",
        },
    )


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
