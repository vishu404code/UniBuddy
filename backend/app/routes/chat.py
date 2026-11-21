from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

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
from app.services.chat import AskTimedOut, ask_question, forward_message_to_faculty
from app.services.chat_retention import cutoff_for, tidy_student_chats_safely
from app.services.providers import get_ai_client, get_data_client
from app.services.postgres_client import PostgresClient

router = APIRouter(prefix="/chat", tags=["chat"])
STUDENT_ONLY = ("student",)


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: PostgresClient = Depends(get_data_client),
    ai: GeminiClient = Depends(get_ai_client),
):
    try:
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
    except AskTimedOut as exc:
        # A visible, retryable error: the UI shows it instead of waiting.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
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
    sb: PostgresClient = Depends(get_data_client),
):
    """Conversations with messages in the last 72 hours. Each visit also tidies one batch of older
    chats into private summaries (see chat_retention). That step never fails this request."""
    try:
        ai = get_ai_client()
    except HTTPException:
        ai = None  # AI not configured: old chats wait for a visit that can summarize them
    await tidy_student_chats_safely(sb=sb, ai=ai, user=session.user)
    cutoff = cutoff_for(datetime.now(timezone.utc))
    recent = await sb.select_as_user(
        session.access_token,
        "messages",
        {"select": "conversation_id", "created_at": f"gte.{cutoff.isoformat()}", "limit": "1000"},
    )
    ids = sorted({str(row["conversation_id"]) for row in recent})
    if not ids:
        return Page[ConversationOut](items=[], total=0, limit=limit, offset=offset)
    rows = await sb.select_as_user(
        session.access_token,
        "conversations",
        {"select": "id,title,created_at", "id": f"in.({','.join(ids)})", "order": "created_at.desc"},
    )
    return Page[ConversationOut](items=rows[offset : offset + limit], total=len(rows), limit=limit, offset=offset)


@router.delete("/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Deletes one of the caller's own conversations and its messages. Other Students' chats are not found."""
    owned = await sb.select_service(
        "conversations", {"select": "id", "id": f"eq.{conversation_id}", "user_id": f"eq.{session.user.id}"}
    )
    if not owned:
        raise HTTPException(status_code=404, detail="Conversation not found")
    await sb.delete_service("conversations", {"id": f"eq.{conversation_id}", "user_id": f"eq.{session.user.id}"})
    return Response(status_code=204)


@router.get("/conversations/{conversation_id}/messages", response_model=Page[MessageOut])
async def list_messages(
    conversation_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    sb: PostgresClient = Depends(get_data_client),
):
    cutoff = cutoff_for(datetime.now(timezone.utc))
    rows, total = await sb.select_page_as_user(
        session.access_token,
        "messages",
        {
            "select": "id,role,content,citations,created_at",
            "conversation_id": f"eq.{conversation_id}",
            "created_at": f"gte.{cutoff.isoformat()}",
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
    sb: PostgresClient = Depends(get_data_client),
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
