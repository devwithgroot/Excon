import io

import pytest

from app.application.seller_intel.document_models import ParseStatus
from app.application.seller_intel.document_parser import (
    DocumentRejected,
    parse_document,
    validate_upload,
)
from app.application.seller_intel.markdown_normalizer import chunk_markdown, html_to_markdown
from app.application.seller_intel.source_registry import SourceRegistry


def _text_pdf(lines: list[str]) -> bytes:
    stream = "BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def test_pdf_text_becomes_markdown_with_page_reference() -> None:
    parsed = parse_document("profile.pdf", _text_pdf(["Company Profile", "We provide cloud inventory software."]))
    assert parsed.status == ParseStatus.parsed
    assert "<!-- page 1 -->" in parsed.markdown
    assert "## Company Profile" in parsed.markdown
    assert "cloud inventory software" in parsed.markdown
    assert parsed.page_count == 1


def test_pdf_without_text_layer_is_failed_not_empty_success() -> None:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    parsed = parse_document("scan.pdf", buffer.getvalue())
    assert parsed.status == ParseStatus.failed
    assert "no_text_layer" in parsed.error


def test_encrypted_pdf_is_reported() -> None:
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(_text_pdf(["Secret"]))))
    writer.encrypt("pw")
    buffer = io.BytesIO()
    writer.write(buffer)
    parsed = parse_document("locked.pdf", buffer.getvalue())
    assert parsed.status == ParseStatus.failed
    assert parsed.error.startswith("encrypted")


def test_docx_keeps_headings_lists_and_tables() -> None:
    from docx import Document

    document = Document()
    document.add_heading("Our Services", level=1)
    document.add_paragraph("Route planning consulting for distributors.")
    document.add_paragraph("Dealer onboarding", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Plan"
    table.rows[0].cells[1].text = "Price"
    table.rows[1].cells[0].text = "Starter"
    table.rows[1].cells[1].text = "Contact us"
    buffer = io.BytesIO()
    document.save(buffer)
    parsed = parse_document("services.docx", buffer.getvalue())
    assert parsed.status == ParseStatus.parsed
    assert "# Our Services" in parsed.markdown
    assert "- Dealer onboarding" in parsed.markdown
    assert "| Plan | Price |" in parsed.markdown
    assert "Our Services" in parsed.sections


def test_xlsx_and_pptx_are_structured() -> None:
    from openpyxl import Workbook
    from pptx import Presentation

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Catalog"
    sheet.append(["Product", "For"])
    sheet.append(["FieldApp", "FMCG distributors"])
    buffer = io.BytesIO()
    workbook.save(buffer)
    xlsx = parse_document("catalog.xlsx", buffer.getvalue())
    assert xlsx.status == ParseStatus.parsed
    assert "## Sheet: Catalog" in xlsx.markdown
    assert "| FieldApp | FMCG distributors |" in xlsx.markdown

    deck = Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[1])
    slide.shapes.title.text = "Why us"
    slide.placeholders[1].text = "Live dealer visibility"
    buffer = io.BytesIO()
    deck.save(buffer)
    pptx = parse_document("pitch.pptx", buffer.getvalue())
    assert pptx.status == ParseStatus.parsed
    assert "## Slide 1: Why us" in pptx.markdown
    assert "- Live dealer visibility" in pptx.markdown


def test_text_formats() -> None:
    assert parse_document("notes.md", b"# ICP\n\nLogistics").markdown.startswith("# ICP")
    csv = parse_document("leads.csv", b"industry,size\nlogistics,50-200\n")
    assert "| industry | size |" in csv.markdown
    assert "```json" in parse_document("facts.json", b'{"industry": "SaaS"}').markdown
    assert parse_document("bad.json", b"{oops").status == ParseStatus.failed
    html = parse_document("page.html", b"<html><body><nav>Menu</nav><h2>About</h2><p>We build apps.</p></body></html>")
    assert "## About" in html.markdown and "Menu" not in html.markdown


def test_corrupt_mismatched_and_unsupported_files() -> None:
    assert parse_document("deck.pptx", b"not a zip").status == ParseStatus.failed
    assert parse_document("fake.pdf", b"hello").error.startswith("content_mismatch")
    assert parse_document("broken.docx", b"PK\x03\x04garbage").status == ParseStatus.failed
    assert parse_document("old.doc", b"abc").status == ParseStatus.unsupported_format
    assert parse_document("empty.txt", b"").status == ParseStatus.empty


def test_validate_upload_rejects_before_storage() -> None:
    assert validate_upload("a.pdf", 10, max_bytes=100) == "pdf"
    for name, size in (("a.doc", 10), ("a.exe", 10), ("a.pdf", 0), ("a.pdf", 101)):
        with pytest.raises(DocumentRejected):
            validate_upload(name, size, max_bytes=100)


def test_html_to_markdown_drops_cookie_banners() -> None:
    markdown = html_to_markdown(
        '<body><div class="cookie-banner">Accept cookies</div><h1>Acme</h1>'
        "<ul><li>Fleet tracking</li></ul><footer>Pune, India</footer></body>"
    )
    assert "Accept cookies" not in markdown
    assert "# Acme" in markdown and "- Fleet tracking" in markdown and "Pune, India" in markdown


def test_chunking_respects_sections() -> None:
    markdown = "\n\n".join(f"## Section {i}\n\n" + ("word " * 60) for i in range(6))
    chunks = chunk_markdown(markdown, 800)
    assert len(chunks) > 1
    assert all(len(chunk) <= 800 for chunk in chunks)
    assert all(chunk.startswith("## Section") for chunk in chunks)


def test_registry_keeps_sources_separate_and_dedupes_identical_bodies() -> None:
    registry = SourceRegistry()
    ok = registry.add_document(parse_document("a.md", b"# A\n\nWe sell CRM."))
    dup = registry.add_document(parse_document("b.md", b"# A\n\nWe  sell CRM."))
    failed = registry.add_document(parse_document("c.pdf", b"nope"))
    assert dup.source_id == ok.source_id
    assert len(registry) == 2
    assert registry.usable() == [ok]
    assert failed.extraction_status == "failed"
