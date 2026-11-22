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

    # Each sentence is checked on its own. A claim that cites no retrieved source, or that its cited sources do
    # not support, is dropped. Only the claims that survive are shown, and only their citations are returned.
    kept: list[str] = []
    cited_all: set[int] = set()
    for bullet, unit in _split_units(raw):
        cited = _cited_numbers(unit, len(evidence))
        if not cited:
            if len(_content_words(unit)) >= MIN_CLAIM_WORDS:
                continue  # an uncited claim: never shown
            kept.append(("- " if bullet else "") + unit)  # a short phrase such as an intro line
            continue
        if not _supported(unit, cited, evidence):
            continue  # cited, but the cited sources do not say it
        cited_all.update(cited)
        kept.append(("- " if bullet else "") + unit)

    if not cited_all:
        return abstain()

    seen: set[tuple[UUID, int | None]] = set()
    citations: list[Citation] = []
    for number in sorted(cited_all):
        source = evidence[number - 1]
        key = (source.document_id, source.page_number)
        if key not in seen:
            seen.add(key)
            citations.append(Citation(document_id=source.document_id, title=source.title, page=source.page_number))
    return Answer(text="\n".join(kept), citations=citations, abstained=False)


# Grounding checks, deterministic and local. They limit what can be shown; they do not prove an answer is right.
# A claim is supported when at least SUPPORT_THRESHOLD of its content words appear in one of the sources it cites.
SUPPORT_THRESHOLD = 0.5
MIN_CLAIM_WORDS = 4
STOPWORDS = frozenset(
    "a an and are as at be been being but by can could did do does for from had has have how i if in into is "
    "it its of on or our should so than that the their them then there these they this to too very was we were "
    "what when where which who why will with would you your about after also any because both each few more "
    "most must not only other over same some such only".split()
)


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in STOPWORDS}


def _split_units(text: str) -> list[tuple[bool, str]]:
    """Lines first (a bullet keeps its marker), then sentences inside each line. Returns (is_bullet, sentence)."""
    units: list[tuple[bool, str]] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        bullet = stripped.startswith(("- ", "* ", "• "))
        body = stripped[2:].strip() if bullet else stripped
        for sentence in re.split(r"(?<=[.!?])\s+", body):
            if sentence.strip():
                units.append((bullet, sentence.strip()))
    return units


def _cited_numbers(unit: str, evidence_count: int) -> list[int]:
    # Accept [1], [1][2] and [1, 2]; a model often writes the last form. Numbers outside the sources are ignored.
    cited = {int(n) for group in CITATION_PATTERN.findall(unit) for n in re.findall(r"\d+", group)}
    return sorted(n for n in cited if 1 <= n <= evidence_count)


def _supported(unit: str, cited: list[int], evidence: list["Evidence"]) -> bool:
    claim = _content_words(CITATION_PATTERN.sub("", unit))
    if not claim:
        return True
    best = max(len(claim & _content_words(evidence[n - 1].content)) / len(claim) for n in cited)
    return best >= SUPPORT_THRESHOLD


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
