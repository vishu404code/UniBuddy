import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

ABSTAIN_MESSAGE = (
    "I couldn't find this in the approved university documents, so I can't answer it reliably. "
    "You can send this question to the relevant faculty."
)
INSUFFICIENT_MARKER = "INSUFFICIENT_EVIDENCE"
CITATION_PATTERN = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

SYSTEM_PROMPT = (
    "You answer questions for a university campus assistant. Use only the numbered SOURCES. "
    "Cite every claim with the source number in square brackets, for example [1]. "
    f"If the sources do not contain the answer, reply with exactly {INSUFFICIENT_MARKER} and nothing else. "
    "Do not use outside knowledge. Do not guess dates, fees, rules or deadlines."
)


class TextGenerator(Protocol):
    async def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class Evidence:
    chunk_id: UUID
    document_id: UUID
    title: str
    page_number: int | None
    content: str
    similarity: float


@dataclass(frozen=True)
class Citation:
    document_id: UUID
    title: str
    page: int | None


@dataclass(frozen=True)
class Answer:
    text: str
    citations: list[Citation]
    abstained: bool


def select_evidence(rows: list[dict[str, Any]], min_similarity: float, limit: int) -> list[Evidence]:
    evidence = [
        Evidence(
            chunk_id=UUID(row["chunk_id"]),
            document_id=UUID(row["document_id"]),
            title=row["title"],
            page_number=row.get("page_number"),
            content=row["content"],
            similarity=float(row["similarity"]),
        )
        for row in rows
        if float(row["similarity"]) >= min_similarity
    ]
    evidence.sort(key=lambda item: item.similarity, reverse=True)
    return evidence[:limit]


def build_user_prompt(question: str, evidence: list[Evidence]) -> str:
    sources = "\n\n".join(
        f"[{number}] {item.title}, page {item.page_number}\n{item.content}"
        for number, item in enumerate(evidence, start=1)
    )
    return f"SOURCES:\n{sources}\n\nQUESTION: {question}"


def abstain() -> Answer:
    return Answer(text=ABSTAIN_MESSAGE, citations=[], abstained=True)


async def answer_question(question: str, evidence: list[Evidence], generator: TextGenerator) -> Answer:
    if not evidence:
        return abstain()

    raw = (await generator.complete(SYSTEM_PROMPT, build_user_prompt(question, evidence))).strip()
    if not raw or INSUFFICIENT_MARKER in raw:
        return abstain()

    # Accept [1], [1][2] and [1, 2]; a model often writes the last form.
    cited = {int(n) for group in CITATION_PATTERN.findall(raw) for n in re.findall(r"\d+", group)}
    cited_numbers = sorted(n for n in cited if 1 <= n <= len(evidence))
    if not cited_numbers:
        return abstain()

    seen: set[tuple[UUID, int | None]] = set()
    citations: list[Citation] = []
    for number in cited_numbers:
        source = evidence[number - 1]
        key = (source.document_id, source.page_number)
        if key not in seen:
            seen.add(key)
            citations.append(Citation(document_id=source.document_id, title=source.title, page=source.page_number))
    return Answer(text=raw, citations=citations, abstained=False)
