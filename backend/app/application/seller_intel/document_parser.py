"""Turn uploaded bytes into normalized Markdown, or an explicit failure status."""

import csv
import io
import json
import logging
from pathlib import Path

from app.application.seller_intel.document_models import ParsedDocument, ParseStatus
from app.application.seller_intel.markdown_normalizer import (
    headings,
    html_to_markdown,
    table_to_markdown,
    text_to_markdown,
    tidy_markdown,
)

logger = logging.getLogger(__name__)

SUPPORTED = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "xlsx",
    ".pptx": "pptx",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
    ".csv": "csv",
    ".json": "json",
    ".html": "html",
    ".htm": "html",
}
LEGACY = {".doc", ".xls", ".ppt"}
ZIP_FORMATS = {"docx", "xlsx", "pptx"}
MAX_SHEET_ROWS = 200
MAX_JSON_CHARS = 20_000


class DocumentRejected(ValueError):
    def __init__(self, message: str, status: ParseStatus = ParseStatus.failed) -> None:
        super().__init__(message)
        self.status = status


def document_format(filename: str) -> str | None:
    return SUPPORTED.get(Path(filename).suffix.lower())


def validate_upload(filename: str, size: int, *, max_bytes: int) -> str:
    """Reject before storing: unknown extension, legacy binary formats, empty or oversized files."""
    suffix = Path(filename).suffix.lower()
    if suffix in LEGACY:
        raise DocumentRejected(
            f"{filename}: legacy {suffix} is not supported; save it as {suffix}x or PDF", ParseStatus.unsupported_format
        )
    fmt = SUPPORTED.get(suffix)
    if fmt is None:
        raise DocumentRejected(f"{filename}: unsupported file type {suffix or '(none)'}", ParseStatus.unsupported_format)
    if size <= 0:
        raise DocumentRejected(f"{filename}: file is empty")
    if size > max_bytes:
        raise DocumentRejected(f"{filename}: file is larger than {max_bytes // 1_000_000} MB")
    return fmt


def parse_document(
    filename: str,
    data: bytes,
    *,
    mime_type: str | None = None,
    storage_path: str | None = None,
    document_id: str | None = None,
) -> ParsedDocument:
    fmt = document_format(filename)
    base = {
        "filename": filename,
        "original_format": fmt or Path(filename).suffix.lower().lstrip(".") or "unknown",
        "mime_type": mime_type,
        "size_bytes": len(data),
        "storage_path": storage_path,
    }
    if document_id:
        base["document_id"] = document_id
    if fmt is None:
        return ParsedDocument(**base, status=ParseStatus.unsupported_format, error="unsupported_format")
    if not data:
        return ParsedDocument(**base, status=ParseStatus.empty, error="empty_file")
    mismatch = _magic_mismatch(fmt, data)
    if mismatch:
        return ParsedDocument(**base, status=ParseStatus.failed, error=mismatch)
    try:
        markdown, page_count = PARSERS[fmt](data)
    except _ParseError as exc:
        return ParsedDocument(**base, status=ParseStatus.failed, error=str(exc))
    except Exception as exc:
        logger.warning("document %s failed to parse: %s", filename, exc)
        return ParsedDocument(**base, status=ParseStatus.failed, error=f"corrupt_or_unreadable: {exc}"[:300])
    markdown = tidy_markdown(markdown)
    if not markdown:
        status, error = ParseStatus.empty, "no_extractable_text"
        if fmt == "pdf":
            status, error = ParseStatus.failed, "no_text_layer (likely scanned; OCR is not configured)"
        return ParsedDocument(**base, status=status, error=error, page_count=page_count)
    return ParsedDocument(
        **base,
        status=ParseStatus.parsed,
        markdown=markdown,
        sections=headings(markdown)[:50],
        page_count=page_count,
    )


class _ParseError(Exception):
    pass


def _magic_mismatch(fmt: str, data: bytes) -> str | None:
    if fmt == "pdf" and not data[:1024].lstrip().startswith(b"%PDF"):
        return "content_mismatch: file does not look like a PDF"
    if fmt in ZIP_FORMATS and not data.startswith(b"PK"):
        return f"content_mismatch: file does not look like a {fmt.upper()}"
    if fmt in {"txt", "md", "csv", "json", "html"} and b"\x00" in data[:4096]:
        return "content_mismatch: binary content in a text file"
    return None


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _pdf(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            if not reader.decrypt(""):
                raise _ParseError("encrypted: password-protected PDF")
        except _ParseError:
            raise
        except Exception as exc:
            raise _ParseError("encrypted: password-protected PDF") from exc
    parts: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            parts.append(f"<!-- page {number} -->\n{text_to_markdown(text)}")
    return "\n\n".join(parts), len(reader.pages)


def _docx(data: bytes) -> tuple[str, int | None]:
    from docx import Document

    document = Document(io.BytesIO(data))
    lines: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        style = (paragraph.style.name or "").lower() if paragraph.style is not None else ""
        if style.startswith("heading"):
            level = "".join(ch for ch in style if ch.isdigit()) or "2"
            lines.append(f"\n{'#' * min(int(level), 6)} {text}\n")
        elif style == "title":
            lines.append(f"\n# {text}\n")
        elif "list" in style:
            lines.append(f"- {text}")
        else:
            lines.append(text + "\n")
    for table in document.tables:
        rows = [[cell.text for cell in row.cells] for row in table.rows]
        rendered = table_to_markdown(rows)
        if rendered:
            lines.append("\n" + rendered + "\n")
    return "\n".join(lines), None


def _xlsx(data: bytes) -> tuple[str, int]:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts: list[str] = []
    for sheet in workbook.worksheets:
        rows = [list(row) for _, row in zip(range(MAX_SHEET_ROWS), sheet.iter_rows(values_only=True))]
        rendered = table_to_markdown(rows)
        if rendered:
            parts.append(f"## Sheet: {sheet.title}\n\n{rendered}")
    count = len(workbook.worksheets)
    workbook.close()
    return "\n\n".join(parts), count


def _pptx(data: bytes) -> tuple[str, int]:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(data))
    parts: list[str] = []
    for number, slide in enumerate(deck.slides, start=1):
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None and slide.shapes.title.has_text_frame else ""
        body: list[str] = []
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    text = "".join(run.text for run in paragraph.runs).strip()
                    if text:
                        body.append(f"- {text}")
            if getattr(shape, "has_table", False) and shape.has_table:
                rows = [[cell.text for cell in row.cells] for row in shape.table.rows]
                body.append(table_to_markdown(rows))
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                body.append(f"\nNotes: {notes}")
        if title or body:
            parts.append(f"## Slide {number}{': ' + title if title else ''}\n\n" + "\n".join(body))
    return "\n\n".join(parts), len(deck.slides)


def _txt(data: bytes) -> tuple[str, None]:
    return text_to_markdown(_decode(data)), None


def _md(data: bytes) -> tuple[str, None]:
    return _decode(data), None


def _csv(data: bytes) -> tuple[str, None]:
    rows = list(csv.reader(io.StringIO(_decode(data))))[:MAX_SHEET_ROWS]
    return table_to_markdown(rows), None


def _json(data: bytes) -> tuple[str, None]:
    try:
        parsed = json.loads(_decode(data))
    except json.JSONDecodeError as exc:
        raise _ParseError(f"corrupt_or_unreadable: invalid JSON ({exc.msg})") from exc
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False)[:MAX_JSON_CHARS]
    return f"```json\n{pretty}\n```", None


def _html(data: bytes) -> tuple[str, None]:
    return html_to_markdown(_decode(data)), None


PARSERS = {
    "pdf": _pdf,
    "docx": _docx,
    "xlsx": _xlsx,
    "pptx": _pptx,
    "txt": _txt,
    "md": _md,
    "csv": _csv,
    "json": _json,
    "html": _html,
}
