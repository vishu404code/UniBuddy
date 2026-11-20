from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

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
from app.services.chat_retention import cutoff_for, tidy_student_chats_safely
from app.services.chat_memory import (
    correct_memory,
    delete_memory,
    list_memories,
    memory_enabled,
    prune_student_memories,
    set_answer_style,
)
from app.schemas.chat import AnswerStyleIn, MemoryOut, MemoryPatch
from fastapi import Response
from app.services.providers import get_ai_client, get_data_client
from app.services.postgres_client import PostgresClient

router = APIRouter(prefix="/chat", tags=["chat"])
STUDENT_ONLY = ("student",)


def _memory_or_404() -> None:
    """With CHAT_MEMORY_CONTEXT_ENABLED off, the memory endpoints do not exist and touch no memory rows."""
    if not memory_enabled():
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/ask", response_model=AskResponse)
async def ask(
    body: AskRequest,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: PostgresClient = Depends(get_data_client),
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
        memory_enabled=memory_enabled(),
        recall_own_chats=body.recall_own_chats,
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
    sb: PostgresClient = Depends(get_data_client),
):
    """Conversations with messages in the last 72 hours. Each visit also tidies one batch of older
    chats into private summaries (see chat_retention). That step never fails this request."""
    try:
        ai = get_ai_client()
    except HTTPException:
        ai = None  # AI not configured: old chats wait for a visit that can summarize them
    await tidy_student_chats_safely(sb=sb, ai=ai, user=session.user)
    if memory_enabled():
        await prune_student_memories(sb=sb, user=session.user)
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


@router.get("/memories", response_model=list[MemoryOut])
async def my_memories(
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Your own private memories, under your own access. Nothing from another Student is returned."""
    _memory_or_404()
    return await list_memories(sb=sb, access_token=session.access_token)


@router.patch("/memories/{memory_id}", response_model=MemoryOut)
async def correct_my_memory(
    memory_id: UUID,
    body: MemoryPatch,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: PostgresClient = Depends(get_data_client),
):
    _memory_or_404()
    row = await correct_memory(sb=sb, user=session.user, memory_id=memory_id, text=body.text, importance=body.importance)
    return MemoryOut(**row)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_my_memory(
    memory_id: UUID,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: PostgresClient = Depends(get_data_client),
):
    _memory_or_404()
    await delete_memory(sb=sb, user=session.user, memory_id=memory_id)
    return Response(status_code=204)


@router.put("/answer-style")
async def choose_answer_style(
    body: AnswerStyleIn,
    session: Annotated[CurrentSession, Depends(session_with_roles(*STUDENT_ONLY))],
    sb: PostgresClient = Depends(get_data_client),
):
    """Presentation only: how answers are written. It never changes what an answer may state."""
    _memory_or_404()
    style = await set_answer_style(sb=sb, user=session.user, style=body.style)
    return {"style": style}
