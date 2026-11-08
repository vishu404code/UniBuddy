from dataclasses import dataclass

import pymupdf

MAX_PAGES = 300


class PdfProcessingError(Exception):
    """The file is not a PDF we can process."""


class PdfHasNoTextError(PdfProcessingError):
    """The PDF has no text layer, so it is probably scanned and would need OCR."""


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str


@dataclass(frozen=True)
class ExtractedText:
    page_count: int
    pages: list[PageText]


def _normalize(raw: str) -> str:
    lines = (line.strip() for line in raw.replace("\x00", "").splitlines())
    return "\n".join(line for line in lines if line)


def extract_pages(data: bytes) -> ExtractedText:
    if not data.startswith(b"%PDF-"):
        raise PdfProcessingError("File is not a PDF")

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfProcessingError("PDF could not be opened (it may be corrupted)") from exc

    try:
        if document.is_encrypted:
            raise PdfProcessingError("Encrypted PDFs are not supported")
        page_count = document.page_count
        if page_count == 0:
            raise PdfProcessingError("PDF has no pages")
        if page_count > MAX_PAGES:
            raise PdfProcessingError(f"PDF has more than {MAX_PAGES} pages")

        pages: list[PageText] = []
        for index in range(page_count):
            text = _normalize(document[index].get_text())
            if text:
                pages.append(PageText(page_number=index + 1, text=text))
    finally:
        document.close()

    if not pages:
        raise PdfHasNoTextError("PDF has no text layer. Scanned PDFs need OCR, which is not enabled yet.")
    return ExtractedText(page_count=page_count, pages=pages)
