import pymupdf
import pytest

from app.ai.chunking import chunk_pages
from app.ai.pdf_extractor import PageText, PdfHasNoTextError, PdfProcessingError, extract_pages


def _pdf(*page_texts: str | None) -> bytes:
    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def test_extracts_text_per_page_and_keeps_original_page_numbers():
    data = _pdf("Fee policy: pay by the second week.", None, "Attendance: 75 percent is required.")

    extracted = extract_pages(data)

    assert extracted.page_count == 3
    assert [(p.page_number, p.text) for p in extracted.pages] == [
        (1, "Fee policy: pay by the second week."),
        (3, "Attendance: 75 percent is required."),
    ]


def test_rejects_bytes_that_are_not_a_pdf():
    with pytest.raises(PdfProcessingError, match="not a PDF"):
        extract_pages(b"hello world")


def test_rejects_corrupted_pdf():
    with pytest.raises(PdfProcessingError, match="corrupted"):
        extract_pages(b"%PDF-1.4\nthis is not a real pdf body")


def test_pdf_without_text_layer_is_reported_as_scanned():
    with pytest.raises(PdfHasNoTextError, match="OCR"):
        extract_pages(_pdf(None))


def test_chunks_keep_page_numbers_and_respect_max_length():
    long_line = " ".join(f"word{i}" for i in range(400))
    pages = [PageText(page_number=2, text=long_line), PageText(page_number=5, text="Short note.")]

    chunks = chunk_pages(pages, max_chars=200, overlap=40)

    assert all(len(c.content) <= 200 for c in chunks)
    assert {c.page_number for c in chunks} == {2, 5}
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].page_number == 5
    assert chunks[-1].content == "Short note."


def test_chunks_overlap_when_a_long_line_is_split():
    text = "".join(str(i % 10) for i in range(500))
    chunks = chunk_pages([PageText(page_number=1, text=text)], max_chars=100, overlap=20)

    assert len(chunks) > 1
    assert chunks[0].content[-20:] == chunks[1].content[:20]


def test_overlap_must_be_smaller_than_chunk_size():
    with pytest.raises(ValueError):
        chunk_pages([PageText(page_number=1, text="x")], max_chars=50, overlap=50)
