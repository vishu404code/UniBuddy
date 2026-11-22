import asyncio
import logging
import re
import time
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.ai.gemini_client import AIServiceError, GeminiClient
from app.ai.rag import (
    MULTI_PART_EVIDENCE,
    Answer,
    answer_question,
    merge_part_evidence,
    select_evidence,
    split_question_parts,
)
from app.schemas.auth import CurrentUser
from app.services.documents import DocumentConflict, DocumentError, DocumentNotFound
from app.services.postgres_client import PostgresClient
from app.services.errors import DataServiceError
from app.services.ai_usage import embedding_model_name, record_usage

MAX_TITLE_LENGTH = 60
# Saved as the answer when the AI service fails. It has no citations, so the student can
# still send the question to faculty. The question itself is never lost.
UNAVAILABLE_MESSAGE = (
    "UniBuddy could not check the documents just now. Try again later, "
    "or send this question to faculty."
)
logger = logging.getLogger("unibuddy.chat")

# Bounds. A model call that stalls becomes the visible "could not check" reply after this long, and
# a whole answer that stalls on the database is reported as an error after the deadline.
MODEL_CALL_TIMEOUT_SECONDS = 15.0
ASK_DEADLINE_SECONDS = 30.0

# Answered without searching or calling the model. Greetings and thanks are checked first, so "hello" never waits.
GREETING_MESSAGE = (
    "Hello! Ask me about your courses, university documents, announcements, or student life. "
    "I answer only from approved university documents and show the page I used."
)
THANKS_MESSAGE = "You're welcome. Ask another question any time."
NO_DOCUMENTS_MESSAGE = (
    "No approved university documents are available for your account yet, so I can't answer this from them. "
    "You can send this question to the relevant faculty."
)
GREETINGS = frozenset({
    "hi", "hello", "hey", "hiya", "yo", "hi there", "hello there", "hey there",
    "good morning", "good afternoon", "good evening", "namaste",
})
THANKS = frozenset({"thanks", "thank you", "thanks a lot", "thank you so much", "thx", "ty"})


class AskTimedOut(Exception):
    """The answer did not finish within ASK_DEADLINE_SECONDS. Nothing was answered; the student should retry."""


@dataclass(frozen=True)
class AskResult:
    conversation_id: UUID
    user_message_id: UUID
    assistant_message_id: UUID
    answer: Answer


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(value) for value in vector) + "]"


class _UsageRecordingGenerator:
    """Passes the answer call through and records its usage metadata only: model, time and token
    counts. No question, answer, user or email is stored. A failure to record never fails the answer."""

    def __init__(self, generator, sb: PostgresClient):
        self._generator = generator
        self._sb = sb

    async def complete(self, system: str, user: str) -> str:
        complete_with_usage = getattr(self._generator, "complete_with_usage", None)
        if complete_with_usage is None:
            return await self._generator.complete(system, user)
        text, usage = await complete_with_usage(system, user)
        await record_usage(
            self._sb,
            operation="answer",
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
        return text


async def _conversation_for_user(sb: PostgresClient, user: CurrentUser, conversation_id: UUID) -> dict:
    rows = await sb.select_service(
        "conversations",
        {"select": "id,user_id", "id": f"eq.{conversation_id}", "user_id": f"eq.{user.id}"},
    )
    if not rows:
        raise DocumentNotFound("Conversation not found")
    return rows[0]


def _normalized_words(question: str) -> str:
    return " ".join(re.findall(r"[a-z]+", question.lower()))


async def _quick_answer(sb: PostgresClient, access_token: str, question: str) -> Answer | None:
    """Answers that need no search and no model call. Returns None when the question must be searched.

    A greeting or thanks is answered directly. If the student cannot see any published, ready document,
    there is nothing to search, so the reply says so at once instead of embedding the question."""
    phrase = _normalized_words(question)
    if phrase and len(phrase.split()) <= 4:
        if phrase in GREETINGS:
            return Answer(text=GREETING_MESSAGE, citations=[], abstained=False)
        if phrase in THANKS:
            return Answer(text=THANKS_MESSAGE, citations=[], abstained=False)
    # Row-level security applies: only documents this student may read are returned.
    visible = await sb.select_as_user(
        access_token,
        "documents",
        {"select": "id", "publication_status": "eq.published", "processing_status": "eq.ready", "limit": "1"},
    )
    if not visible:
        return Answer(text=NO_DOCUMENTS_MESSAGE, citations=[], abstained=True)
    return None


async def _timed(timings: dict[str, float], name: str, awaitable):
    begin = time.perf_counter()
    try:
        return await awaitable
    finally:
        timings[name] = (time.perf_counter() - begin) * 1000


async def _model_call(label: str, awaitable):
    """Bounds one model call. A stalled call is reported as an AI failure, which gets the visible reply."""
    try:
        return await asyncio.wait_for(awaitable, timeout=MODEL_CALL_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise AIServiceError(f"Gemini {label} timed out after {MODEL_CALL_TIMEOUT_SECONDS:.0f}s") from exc


async def _answer(
    *,
    sb: PostgresClient,
    ai: GeminiClient,
    user: CurrentUser,
    access_token: str,
    question: str,
    conversation_id: UUID,
    user_message_id: UUID,
    top_k: int,
    min_similarity: float,
    timings: dict[str, float],
    started: float,
) -> Answer:
    quick = await _quick_answer(sb, access_token, question)
    if quick is not None:
        await sb.insert_service(
            "messages",
            [{"id": str(user_message_id), "conversation_id": str(conversation_id), "role": "user", "content": question}],
        )
        logger.info("answer: quick=true abstained=%s total_ms=%d", quick.abstained, (time.perf_counter() - started) * 1000)
        return quick

    # The question is saved while its query is embedded, so the two waits overlap.
    parts = split_question_parts(question)
    embed_task = asyncio.ensure_future(_timed(timings, "embed_ms", _model_call(
        "embedding", asyncio.gather(*(ai.embed_query(part) for part in parts)),
    )))
    try:
        # The save always finishes before the answer is written, so the question is never stored after its reply.
        await sb.insert_service(
            "messages",
            [{"id": str(user_message_id), "conversation_id": str(conversation_id), "role": "user", "content": question}],
        )
        vectors = await embed_task
        await record_usage(sb, operation="query_embedding", model=embedding_model_name(ai), request_count=len(parts))
    except BaseException:
        embed_task.cancel()
        raise
    # Each part of a multi-part question is searched on its own, under the same access rules (RLS).
    match_rows = await _timed(timings, "match_ms", asyncio.gather(*(
        sb.rpc_as_user(
            access_token,
            "match_document_chunks",
            {
                "query_embedding": _vector_literal(vector),
                "match_count": top_k,
                "min_similarity": min_similarity,
            },
        )
        for vector in vectors
    )))
    per_part = [select_evidence(rows, min_similarity=min_similarity, limit=top_k) for rows in match_rows]
    evidence = per_part[0] if len(per_part) == 1 else merge_part_evidence(per_part, limit=MULTI_PART_EVIDENCE)
    answer = await _timed(timings, "answer_ms", _model_call(
        "answer", answer_question(question, evidence, _UsageRecordingGenerator(ai, sb)),
    ))
    # Counts and durations only, never the question or the answer.
    logger.info(
        "answer: campus_assigned=%s evidence=%d citations=%d abstained=%s total_ms=%d embed_ms=%d match_ms=%d answer_ms=%d",
        user.campus_id is not None, len(evidence), len(answer.citations), answer.abstained,
        (time.perf_counter() - started) * 1000, timings.get("embed_ms", 0), timings.get("match_ms", 0),
        timings.get("answer_ms", 0),
    )
    return answer


async def ask_question(
    *,
    sb: PostgresClient,
    ai: GeminiClient,
    user: CurrentUser,
    access_token: str,
    question: str,
    conversation_id: UUID | None,
    top_k: int,
    min_similarity: float,
) -> AskResult:
    question = question.strip()
    if not question:
        raise DocumentError("Question must not be empty")

    if conversation_id is None:
        conversation_id = uuid4()
        await sb.insert_service(
            "conversations",
            [{"id": str(conversation_id), "user_id": str(user.id), "title": question[:MAX_TITLE_LENGTH]}],
        )
    else:
        await _conversation_for_user(sb, user, conversation_id)

    user_message_id = uuid4()
    timings: dict[str, float] = {}
    started = time.perf_counter()

    try:
        async with asyncio.timeout(ASK_DEADLINE_SECONDS):
            try:
                answer = await _answer(
                    sb=sb, ai=ai, user=user, access_token=access_token, question=question,
                    conversation_id=conversation_id, user_message_id=user_message_id,
                    top_k=top_k, min_similarity=min_similarity, timings=timings, started=started,
                )
            except AIServiceError as exc:
                logger.warning("Question %s could not be answered: %s", user_message_id, exc)
                answer = Answer(text=UNAVAILABLE_MESSAGE, citations=[], abstained=True)
    except TimeoutError as exc:
        logger.warning("Question %s passed the %.0fs answer deadline", user_message_id, ASK_DEADLINE_SECONDS)
        raise AskTimedOut("The answer took too long. Please try again.") from exc

    assistant_message_id = uuid4()
    await sb.insert_service(
        "messages",
        [
            {
                "id": str(assistant_message_id),
                "conversation_id": str(conversation_id),
                "role": "assistant",
                "content": answer.text,
                "citations": [
                    {"document_id": str(c.document_id), "title": c.title, "page": c.page}
                    for c in answer.citations
                ],
            }
        ],
    )
    return AskResult(
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        answer=answer,
    )


async def forward_message_to_faculty(
    *,
    sb: PostgresClient,
    user: CurrentUser,
    message_id: UUID,
    department_id: UUID | None,
    priority: str,
    description: str | None,
) -> dict:
    if user.campus_id is None:
        raise DocumentError("Your account has no campus assigned")

    rows = await sb.select_service(
        "messages",
        {"select": "id,role,content,conversation_id", "id": f"eq.{message_id}"},
    )
    if not rows:
        raise DocumentNotFound("Message not found")
    message = rows[0]
    await _conversation_for_user(sb, user, UUID(str(message["conversation_id"])))

    if message["role"] != "user":
        raise DocumentError("Only a student question can be forwarded")

    existing = await sb.select_service(
        "tickets",
        {"select": "id,ticket_number", "source_message_id": f"eq.{message_id}"},
    )
    if existing:
        raise DocumentConflict(f"This question was already forwarded as {existing[0]['ticket_number']}")

    # No department is allowed. The ticket then goes to the campus queue, which Authority can see.
    if department_id is not None:
        department = await sb.select_service(
            "departments",
            {"select": "id", "id": f"eq.{department_id}", "campus_id": f"eq.{user.campus_id}"},
        )
        if not department:
            raise DocumentError("Department does not belong to your campus")

    question = message["content"]
    ticket_id = uuid4()
    try:
        await sb.insert_service(
            "tickets",
            [
                {
                    "id": str(ticket_id),
                    "student_id": str(user.id),
                    "campus_id": str(user.campus_id),
                    "department_id": str(department_id) if department_id is not None else None,
                    "subject": question[:120],
                    "question": question,
                    "description": description,
                    "priority": priority,
                    "status": "submitted",
                    "source_message_id": str(message_id),
                }
            ],
        )
    except DataServiceError as exc:
        if exc.status_code == 409:
            raise DocumentConflict("This question was already forwarded to faculty") from exc
        raise
    ticket = (await sb.select_service(
        "tickets",
        {"select": "id,ticket_number,status", "id": f"eq.{ticket_id}"},
    ))[0]
    await sb.insert_service(
        "notifications",
        [
            {
                "id": str(uuid4()),
                "user_id": str(user.id),
                "text": f"Your question was sent to faculty as ticket {ticket['ticket_number']}.",
                "ticket_id": str(ticket_id),
            }
        ],
    )
    return ticket
