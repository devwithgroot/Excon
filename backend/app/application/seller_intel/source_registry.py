import hashlib
import re

from app.application.seller_intel.document_models import IntelSourceType, ParsedDocument, Source


def content_fingerprint(markdown: str) -> str:
    normalized = re.sub(r"\s+", " ", markdown.lower()).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class SourceRegistry:
    """Every page, document and search hit stays an individual, addressable source."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}
        self._fingerprints: dict[str, str] = {}

    def add(self, source: Source) -> Source:
        """Add a source; an identical body under a different URL resolves to the first source."""
        if source.normalized_markdown.strip():
            fingerprint = content_fingerprint(source.normalized_markdown)
            existing = self._fingerprints.get(fingerprint)
            if existing:
                return self._sources[existing]
            self._fingerprints[fingerprint] = source.source_id
        self._sources[source.source_id] = source
        return source

    def add_document(self, document: ParsedDocument) -> Source:
        return self.add(
            Source(
                source_id=f"doc_{document.document_id[:12]}",
                source_type=IntelSourceType.document,
                source_name=document.filename,
                original_content_reference=document.storage_path or document.document_id,
                normalized_markdown=document.markdown,
                extraction_status="pending" if document.usable else document.status.value,
                error=document.error,
            )
        )

    def get(self, source_id: str) -> Source | None:
        return self._sources.get(source_id)

    def all(self) -> list[Source]:
        return list(self._sources.values())

    def usable(self) -> list[Source]:
        return [source for source in self._sources.values() if source.normalized_markdown.strip() and not source.error]

    def of_type(self, source_type: IntelSourceType) -> list[Source]:
        return [source for source in self._sources.values() if source.source_type == source_type]

    def mark(self, source_id: str, status: str, error: str | None = None) -> None:
        source = self._sources.get(source_id)
        if source is not None:
            self._sources[source_id] = source.model_copy(update={"extraction_status": status, "error": error})

    def __len__(self) -> int:
        return len(self._sources)
