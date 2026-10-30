import re

from bs4 import BeautifulSoup
from markdownify import markdownify

NOISE_TAGS = ("script", "style", "noscript", "svg", "iframe", "form", "nav", "button", "template")
NOISE_MARKERS = ("cookie", "consent", "gdpr", "newsletter", "modal", "popup", "skip-link")


def page_title(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return re.sub(r"\s+", " ", soup.title.string).strip() or None
    heading = soup.find("h1")
    return heading.get_text(" ", strip=True) if heading else None


def html_to_markdown(html: str) -> str:
    """Keep headings, lists and tables; drop navigation, banners and link targets."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        if getattr(tag, "decomposed", False) or tag.attrs is None:
            continue
        marker = " ".join([tag.get("id") or "", *(tag.get("class") or [])]).lower()
        if marker and any(word in marker for word in NOISE_MARKERS):
            tag.decompose()
    body = soup.body or soup
    markdown = markdownify(str(body), heading_style="ATX", strip=["a", "img"], bullets="-")
    return tidy_markdown(markdown)


def text_to_markdown(text: str) -> str:
    """Promote short title-like lines in extracted plain text to headings."""
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            lines.append("")
            continue
        if _looks_like_heading(line):
            lines.extend(["", f"## {line.rstrip(':')}", ""])
        else:
            lines.append(line)
    return tidy_markdown("\n".join(lines))


def table_to_markdown(rows: list[list[object]]) -> str:
    cleaned = [[_cell(value) for value in row] for row in rows if any(_cell(v) for v in row)]
    if not cleaned:
        return ""
    width = max(len(row) for row in cleaned)
    cleaned = [row + [""] * (width - len(row)) for row in cleaned]
    header, *body = cleaned
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * width) + " |"]
    out.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(out)


def tidy_markdown(markdown: str) -> str:
    text = markdown.replace("\r\n", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def headings(markdown: str) -> list[str]:
    return [match.group(2).strip() for match in re.finditer(r"^(#{1,6})\s+(.+)$", markdown, flags=re.M)]


def chunk_markdown(markdown: str, max_chars: int) -> list[str]:
    """Split on headings, then paragraphs, so a chunk never cuts a section mid-sentence."""
    if len(markdown) <= max_chars:
        return [markdown] if markdown.strip() else []
    sections = re.split(r"(?m)^(?=#{1,3}\s)", markdown)
    chunks: list[str] = []
    current = ""
    for section in sections:
        pieces = [section] if len(section) <= max_chars else _split_paragraphs(section, max_chars)
        for piece in pieces:
            if current and len(current) + len(piece) > max_chars:
                chunks.append(current.strip())
                current = ""
            current += piece
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _split_paragraphs(section: str, max_chars: int) -> list[str]:
    out: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", section):
        paragraph = paragraph.strip() + "\n\n"
        while len(paragraph) > max_chars:
            out.append(paragraph[:max_chars])
            paragraph = paragraph[max_chars:]
        if current and len(current) + len(paragraph) > max_chars:
            out.append(current)
            current = ""
        current += paragraph
    if current:
        out.append(current)
    return out


def _looks_like_heading(line: str) -> bool:
    if len(line) > 70 or len(line) < 3 or line.endswith((".", ",", ";")):
        return False
    words = line.rstrip(":").split()
    if not 1 <= len(words) <= 8 or not any(ch.isalpha() for ch in line):
        return False
    return line.isupper() or line.istitle() or line.endswith(":")


def _cell(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).replace("|", "/").strip()
