import io
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

import pymupdf

MAX_PAGES = 300


class PdfProcessingError(Exception):
    """The file cannot be processed as a valid university document."""


class PdfHasNoTextError(PdfProcessingError):
    """The document has no text layer, so it is probably scanned and would need OCR."""


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


def extract_docx(data: bytes) -> ExtractedText:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml_content = zf.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            paragraphs = []
            for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [
                    t.text
                    for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                    if t.text
                ]
                if texts:
                    paragraphs.append("".join(texts))
            full_text = _normalize("\n\n".join(paragraphs))
            if not full_text:
                raise PdfHasNoTextError("DOCX document contains no readable text")
            return ExtractedText(page_count=1, pages=[PageText(page_number=1, text=full_text)])
    except Exception as exc:
        raise PdfProcessingError(f"Could not read DOCX document: {exc}") from exc


def extract_txt(data: bytes) -> ExtractedText:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except Exception as exc:
            raise PdfProcessingError("Text file encoding could not be determined") from exc
    cleaned = _normalize(text)
    if not cleaned:
        raise PdfHasNoTextError("Text file is empty")
    return ExtractedText(page_count=1, pages=[PageText(page_number=1, text=cleaned)])


def extract_raw_text(text: str) -> ExtractedText:
    cleaned = _normalize(text)
    if not cleaned:
        raise PdfHasNoTextError("Text content is empty")
    return ExtractedText(page_count=1, pages=[PageText(page_number=1, text=cleaned)])


def extract_pages(
    data: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> ExtractedText:
    if (filename and filename.lower().endswith(".txt")) or content_type == "text/plain":
        return extract_txt(data)
    if (filename and filename.lower().endswith(".docx")) or (
        content_type
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return extract_docx(data)

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
