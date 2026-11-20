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


# Presentation only. A Student may choose one of these styles; the text is fixed here, never taken from chat
# history, and it says nothing about content. Facts still come only from the numbered SOURCES.
ANSWER_STYLES = {
    "concise": "Keep the answer as short as the sources allow: at most three bullets.",
    "plain_language": "Use plain words and short sentences. Do not add anything the sources do not say.",
}

# Numbers, and month or weekday names (compared by their first three letters). "may" is left out: it is a verb.
_WORD = re.compile(r"\d+(?:\.\d+)?|[a-z]+")
_CITATION_MARKER = re.compile(r"\[[\d,\s]+\]")
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}\b)")
_DATE_NAMES = frozenset({
    "january", "jan", "february", "feb", "march", "mar", "april", "apr", "june", "jun", "july", "jul",
    "august", "aug", "september", "sept", "sep", "october", "oct", "november", "nov", "december", "dec",
    "monday", "mon", "tuesday", "tue", "tues", "wednesday", "wed", "thursday", "thu", "thur", "thurs",
    "friday", "fri", "saturday", "sat", "sunday", "sun",
})


def _number_tokens(text: str) -> set[str]:
    tokens = set()
    for word in _WORD.findall(_THOUSANDS.sub("", text.lower())):
        if word[:1].isdigit():
            tokens.add(word)
        elif word in _DATE_NAMES:
            tokens.add(word[:3])
    return tokens


# Every sentence must share most of its content words with the text of the sources it cites. This catches a claim
# the sources do not support, whatever the topic, without a list of topics. Common function words are ignored.
SUPPORT_THRESHOLD = 0.6
_CONTENT_WORD = re.compile(r"[a-z]{4,}")
_FUNCTION_WORDS = frozenset({
    "that", "this", "with", "from", "have", "will", "your", "they", "them", "their", "there", "which", "when",
    "what", "into", "also", "only", "each", "such", "than", "then", "been", "were", "does", "should", "could",
    "would", "must", "about", "after", "before", "these", "those", "where", "while", "other", "more", "most",
    "some", "any", "all", "are", "the", "and", "for", "you", "can", "not", "but", "its", "one", "two", "let",
})


def _stem(word: str) -> str:
    return word[:-1] if word.endswith("s") and len(word) > 4 else word


def _content_words(text: str) -> set[str]:
    return {_stem(word) for word in _CONTENT_WORD.findall(text.lower()) if word not in _FUNCTION_WORDS}


def _sentences(answer: str) -> list[str]:
    text = _CITATION_MARKER.sub(" ", answer)
    parts = re.split(r"\n\s*[-*•]\s*|(?<=[.!?])\s+|\n", text)
    return [part.strip(" -*•") for part in parts if part.strip(" -*•")]


# Logical operators reverse a claim when they change: negation, order in time, comparison, obligation and scope.
# A sentence may use one only if the cited text uses it too. "applies before 15 September" is refused when the
# source says "applies after 15 September". This is a fixed list of operators, not a list of topics.
_OPERATORS = re.compile(
    r"\b(not|no|never|none|nor|without|cannot|before|after|until|since|earlier|later|more|less|fewer|higher|"
    r"lower|greater|smaller|larger|must|may|only|always|every|all)\b|(n't)\b",
    re.IGNORECASE,
)


def _operators(text: str) -> set[str]:
    return {match.group(0).lower() for match in _OPERATORS.finditer(text)}


def claims_are_supported(answer: str, cited_text: str) -> bool:
    """A refusal heuristic, NOT proof of correctness. It refuses a sentence when it uses a logical operator the
    cited text does not use, or when most of its content words are missing from the cited text. It can still pass
    a claim whose words all appear in the source but whose meaning differs in a way no operator shows."""
    source_words = _content_words(cited_text)
    source_operators = _operators(cited_text)
    for sentence in _sentences(answer):
        if _operators(sentence) - source_operators:
            return False
        words = _content_words(sentence)
        if words and len(words & source_words) / len(words) < SUPPORT_THRESHOLD:
            return False
    return True


def numbers_are_grounded(answer: str, cited_text: str) -> bool:
    """Every number, date and weekday the answer states must appear in the text of the sources it cites.
    This is structural: it needs no list of topics or keywords, and it applies to every answer, not only
    to answers that use personal context. Citation markers such as [1] are not counted."""
    return _number_tokens(_CITATION_MARKER.sub(" ", answer)) <= _number_tokens(cited_text)


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


async def answer_question(
    question: str, evidence: list[Evidence], generator: TextGenerator, answer_style: str | None = None
) -> Answer:
    if not evidence:
        return abstain()

    # The style is an optional presentation instruction. Unknown values are ignored, never passed through.
    style_line = ANSWER_STYLES.get(answer_style or "")
    system = f"{SYSTEM_PROMPT} {style_line}" if style_line else SYSTEM_PROMPT
    raw = (await generator.complete(system, build_user_prompt(question, evidence))).strip()
    if not raw or INSUFFICIENT_MARKER in raw:
        return abstain()

    # Accept [1], [1][2] and [1, 2]; a model often writes the last form.
    cited = {int(n) for group in CITATION_PATTERN.findall(raw) for n in re.findall(r"\d+", group)}
    cited_numbers = sorted(n for n in cited if 1 <= n <= len(evidence))
    if not cited_numbers:
        return abstain()
    cited_text = " ".join(evidence[number - 1].content for number in cited_numbers)
    if not numbers_are_grounded(raw, cited_text) or not claims_are_supported(raw, cited_text):
        return abstain()  # a number, date or claim that the cited sources do not state

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
