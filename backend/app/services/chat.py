import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from app.ai.gemini_client import AIServiceError, GeminiClient
from app.ai.rag import Answer, answer_question, select_evidence
from app.schemas.auth import CurrentUser
from app.services.documents import DocumentConflict, DocumentError, DocumentNotFound
from app.services.postgres_client import PostgresClient
from app.services.errors import DataServiceError

MAX_TITLE_LENGTH = 60
# Saved as the answer when the AI service fails. It has no citations, so the student can
# still send the question to faculty. The question itself is never lost.
UNAVAILABLE_MESSAGE = (
    "UniBuddy could not check the documents just now. Try again later, "
    "or send this question to faculty."
)
logger = logging.getLogger("unibuddy.chat")


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
        try:
            await self._sb.insert_service(
                "ai_usage_events",
                [
                    {
                        "id": str(uuid4()),
                        "operation": "answer",
                        "model": usage.model,
                        "request_count": 1,
                        "input_tokens": usage.input_tokens,
                        "output_tokens": usage.output_tokens,
                    }
                ],
            )
        except Exception:
            logger.warning("Gemini usage metadata could not be recorded")
        return text


async def _conversation_for_user(sb: PostgresClient, user: CurrentUser, conversation_id: UUID) -> dict:
    rows = await sb.select_service(
        "conversations",
        {"select": "id,user_id", "id": f"eq.{conversation_id}", "user_id": f"eq.{user.id}"},
    )
    if not rows:
        raise DocumentNotFound("Conversation not found")
    return rows[0]


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
    await sb.insert_service(
        "messages",
        [{"id": str(user_message_id), "conversation_id": str(conversation_id), "role": "user", "content": question}],
    )

    try:
        query_vector = await ai.embed_query(question)
        rows = await sb.rpc_as_user(
            access_token,
            "match_document_chunks",
            {
                "query_embedding": _vector_literal(query_vector),
                "match_count": top_k,
                "min_similarity": min_similarity,
            },
        )
        evidence = select_evidence(rows, min_similarity=min_similarity, limit=top_k)
        answer = await answer_question(question, evidence, _UsageRecordingGenerator(ai, sb))
    except AIServiceError as exc:
        logger.warning("Question %s could not be answered: %s", user_message_id, exc)
        answer = Answer(text=UNAVAILABLE_MESSAGE, citations=[], abstained=True)

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
    department_id: UUID,
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
                    "department_id": str(department_id),
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
