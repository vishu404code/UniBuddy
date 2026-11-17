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
    "Do not use outside knowledge. Do not guess dates, fees, rules or deadlines. "
    "If the question has several parts, answer every part and cite each one. If a part is not in the sources, say so for that part. "
    "Keep the answer short and plain: at most 5 short bullets (use '-') or 2 short paragraphs. "
    "No headings, no tables, no code blocks."
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


def _as_uuid(value: Any) -> UUID:
    # The database driver already returns UUID objects; accept text ids from other callers too.
    return value if isinstance(value, UUID) else UUID(str(value))


def select_evidence(rows: list[dict[str, Any]], min_similarity: float, limit: int) -> list[Evidence]:
    evidence = [
        Evidence(
            chunk_id=_as_uuid(row["chunk_id"]),
            document_id=_as_uuid(row["document_id"]),
            title=row["title"],
            page_number=row.get("page_number"),
            content=row["content"],
            similarity=float(row["similarity"]),
        )
        for row in rows
        if float(row["similarity"]) >= min_similarity
    ]
    evidence.sort(key=lambda item: item.similarity, reverse=True)
    # A copy of the same file stores the same text on the same page. Keep the best-matching copy of each page
    # so the limit is spent on different passages. Same text on different pages is kept (boilerplate can repeat).
    unique: list[Evidence] = []
    seen: set[tuple[int | None, str]] = set()
    for item in evidence:
        key = (item.page_number, " ".join(item.content.split()))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:limit]


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


# Several questions in one message ("A, and how long B?") need each part searched on its own. A single
# search for the whole sentence favours one part and drops the other. Measured on the published documents:
# complex questions reached 0.75 page recall in the top five and 1.00 when each part was searched.
_PART_SPLIT = re.compile(r",\s+and\s+|;\s+", re.IGNORECASE)
MAX_PARTS = 3
# Sources sent to the model for a multi-part question: enough for each part, bounded for speed and cost.
MULTI_PART_EVIDENCE = 8
MIN_PART_LENGTH = 12


def split_question_parts(question: str) -> list[str]:
    parts = [p.strip(" ?.") for p in _PART_SPLIT.split(question.strip())]
    parts = [p for p in parts if len(p) >= MIN_PART_LENGTH]
    if len(parts) < 2:
        return [question.strip()]
    return parts[:MAX_PARTS]


def merge_part_evidence(per_part: list[list[Evidence]], limit: int) -> list[Evidence]:
    """Takes the best source of each part in turn, so no part is crowded out. Repeats of the same page and text
    are kept once."""
    merged: list[Evidence] = []
    seen: set[tuple[int | None, str]] = set()
    rank = 0
    while len(merged) < limit and any(rank < len(part) for part in per_part):
        for part in per_part:
            if rank < len(part) and len(merged) < limit:
                item = part[rank]
                key = (item.page_number, " ".join(item.content.split()))
                if key not in seen:
                    seen.add(key)
                    merged.append(item)
        rank += 1
    return merged
