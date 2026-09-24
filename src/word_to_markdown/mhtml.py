"""Parse Confluence "Export to Word" MHTML documents.

Confluence's ``exportword`` endpoint does not produce a binary Word file; it
produces an **MHTML** (``multipart/related``) container:

* one ``text/html`` part (usually quoted-printable) — the real content
* zero or more additional parts — embedded images, referenced from the HTML by
  ``cid:`` (Content-ID) or ``file:///`` (Content-Location) URLs

This module detects that shape and pulls it apart using only the standard
library, so the rest of the tool can work with plain HTML plus a list of image
payloads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email import message_from_bytes
from email.message import Message
from pathlib import Path

# Bytes we sniff from the head of a file to decide whether it is MHTML.
_SNIFF_LEN = 2048


@dataclass
class ImagePart:
    """A single embedded (usually image) part from an MHTML container."""

    content_type: str
    data: bytes
    content_id: str | None = None
    content_location: str | None = None


@dataclass
class MhtmlDocument:
    """The decoded HTML plus any embedded parts of an MHTML file."""

    html: str
    images: list[ImagePart] = field(default_factory=list)


def is_mhtml(path: Path) -> bool:
    """Return ``True`` if ``path`` looks like an MHTML/MIME container.

    We only read the first couple of kilobytes and look for the MIME headers
    Confluence emits, so this stays cheap and never loads a whole file just to
    classify it.
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(_SNIFF_LEN)
    except OSError:
        return False
    lowered = head.lower()
    if b"mime-version:" in lowered and b"multipart/related" in lowered:
        return True
    # Some exports omit MIME-Version; a multipart/related header is enough.
    return b"content-type: multipart/related" in lowered


def parse_mhtml(path: Path) -> MhtmlDocument:
    """Parse an MHTML file into its HTML body and embedded image parts.

    The first ``text/html`` part found (depth-first) is treated as the document
    body. Every other leaf part is captured as an :class:`ImagePart` keyed by
    its Content-ID and/or Content-Location so callers can resolve references.
    """
    raw = path.read_bytes()
    message = message_from_bytes(raw)

    html: str | None = None
    images: list[ImagePart] = []

    for part in _walk_leaves(message):
        content_type = (part.get_content_type() or "").lower()
        if html is None and content_type == "text/html":
            html = _decode_text_part(part)
            continue
        images.append(_build_image_part(part, content_type))

    if html is None:
        raise ValueError(f"no text/html part found in MHTML file: {path}")

    return MhtmlDocument(html=html, images=images)


def _walk_leaves(message: Message):
    """Yield every non-multipart leaf part of a message, depth-first."""
    if message.is_multipart():
        for sub in message.get_payload():
            yield from _walk_leaves(sub)
    else:
        yield message


def _decode_text_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        # Not transfer-encoded in a way we can decode; fall back to raw string.
        return str(part.get_payload())
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _build_image_part(part: Message, content_type: str) -> ImagePart:
    data = part.get_payload(decode=True) or b""
    return ImagePart(
        content_type=content_type or "application/octet-stream",
        data=data,
        content_id=_normalise_content_id(part.get("Content-ID")),
        content_location=_clean_header(part.get("Content-Location")),
    )


def _normalise_content_id(raw: str | None) -> str | None:
    """Strip the surrounding angle brackets from a Content-ID header."""
    cleaned = _clean_header(raw)
    if cleaned and cleaned.startswith("<") and cleaned.endswith(">"):
        cleaned = cleaned[1:-1]
    return cleaned or None


def _clean_header(raw: str | None) -> str | None:
    if raw is None:
        return None
    # Headers can be folded across lines; collapse whitespace.
    return " ".join(raw.split()).strip() or None
