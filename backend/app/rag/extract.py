"""Document text extraction for the scientific knowledge base.

Supported: plain text, Markdown, HTML (converted to text), PDF (via pypdf).
Binary or unsupported formats raise a typed validation error rather than being
silently accepted. Extraction never reaches out to arbitrary URLs; ingestion is
an explicit operator action with a path or supplied text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import ValidationError
from app.core.geometry import safe_join


@dataclass
class ExtractedDocument:
    text: str
    pages: list[str] = field(default_factory=list)
    title_hint: str | None = None
    extraction_method: str = "text"


_TEXT_SUFFIXES = {".txt", ".text"}
_MARKDOWN_SUFFIXES = {".md", ".markdown"}
_HTML_SUFFIXES = {".html", ".htm"}
_PDF_SUFFIXES = {".pdf"}


def extract_path(path: Path, *, allowed_roots: list[Path] | None = None) -> ExtractedDocument:
    if allowed_roots:
        resolved = path.resolve()
        if not any(resolved == root.resolve() or root.resolve() in resolved.parents for root in allowed_roots):
            raise ValidationError("Document path is outside configured ingestion roots")
    if not path.exists() or not path.is_file():
        raise ValidationError(f"Document does not exist: {path.name}")
    suffix = path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return ExtractedDocument(text=path.read_text(encoding="utf-8", errors="replace"), extraction_method="plain_text")
    if suffix in _MARKDOWN_SUFFIXES:
        return ExtractedDocument(
            text=path.read_text(encoding="utf-8", errors="replace"),
            extraction_method="markdown",
            title_hint=_first_markdown_heading(path.read_text(encoding="utf-8", errors="replace")),
        )
    if suffix in _HTML_SUFFIXES:
        import re

        html = path.read_text(encoding="utf-8", errors="replace")
        # Strip scripts/styles, then tags; collapse whitespace. A full HTML parser
        # is unnecessary for scientific documentation ingestion.
        html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        return ExtractedDocument(text=text, extraction_method="html")
    if suffix in _PDF_SUFFIXES:
        try:
            from pypdf import PdfReader
        except ImportError as exc:  # pragma: no cover - dependency declared
            raise ValidationError("PDF extraction requires the 'pypdf' package") from exc
        reader = PdfReader(str(path))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
        text = "\n\n".join(p for p in pages if p)
        if not text.strip():
            raise ValidationError("PDF contains no extractable text (scanned image PDFs are not supported)")
        title = None
        try:
            meta_title = (reader.metadata or {}).get("/Title")
            if meta_title:
                title = str(meta_title)
        except Exception:  # noqa: BLE001
            title = None
        return ExtractedDocument(text=text, pages=pages, title_hint=title, extraction_method="pdf")
    raise ValidationError(
        f"Unsupported document format '{suffix}'",
        detail={"supported": sorted(_TEXT_SUFFIXES | _MARKDOWN_SUFFIXES | _HTML_SUFFIXES | _PDF_SUFFIXES)},
    )


def resolve_document_path(raw: str, *, roots: list[Path]) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    for root in roots:
        try:
            resolved = safe_join(root, raw)
        except ValueError:
            continue
        if resolved.exists():
            return resolved
    raise ValidationError(
        "Relative document path was not found under configured RAG roots",
        detail={"roots": [str(r) for r in roots]},
    )


def _first_markdown_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None
