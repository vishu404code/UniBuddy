from dataclasses import dataclass

from app.ai.pdf_extractor import PageText


@dataclass(frozen=True)
class Chunk:
    chunk_index: int
    page_number: int
    content: str


def _windows(text: str, max_chars: int, overlap: int) -> list[str]:
    step = max_chars - overlap
    pieces = []
    start = 0
    while True:
        pieces.append(text[start : start + max_chars])
        if start + max_chars >= len(text):
            break
        start += step
    return pieces


def _page_pieces(text: str, max_chars: int, overlap: int) -> list[str]:
    """Split one page into pieces no longer than max_chars, keeping lines whole when possible."""
    pieces: list[str] = []
    for line in text.split("\n"):
        if len(line) <= max_chars:
            pieces.append(line)
        else:
            pieces.extend(_windows(line, max_chars, overlap))
    return pieces


def _pack(pieces: list[str], max_chars: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
        elif len(current) + 1 + len(piece) <= max_chars:
            current = f"{current}\n{piece}"
        else:
            chunks.append(current)
            tail = current[-overlap:] if overlap else ""
            candidate = f"{tail}\n{piece}" if tail else piece
            current = candidate if len(candidate) <= max_chars else piece
    if current:
        chunks.append(current)
    return chunks


def chunk_pages(pages: list[PageText], max_chars: int, overlap: int) -> list[Chunk]:
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be >= 0 and smaller than max_chars")

    chunks: list[Chunk] = []
    for page in pages:
        pieces = _page_pieces(page.text, max_chars, overlap)
        for content in _pack(pieces, max_chars, overlap):
            chunks.append(Chunk(chunk_index=len(chunks), page_number=page.page_number, content=content))
    return chunks
