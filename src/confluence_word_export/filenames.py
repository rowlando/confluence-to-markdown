"""Filename parsing, sanitisation, and collision handling.

This module handles two related concerns:

* deriving safe local file and directory names from untrusted Confluence page
  titles and server-provided filenames (PRD section 13);
* parsing the ``Content-Disposition`` header returned by the Word export
  endpoint, including RFC 5987 ``filename*`` values.
"""

from __future__ import annotations

import os
import re
from urllib.parse import unquote

# Maximum length for a single path segment (leaving room for collision suffixes
# and extensions well within the common 255-byte filesystem limit).
MAX_NAME_LENGTH = 180

# Characters that are invalid on common filesystems (Windows is the strictest).
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Content types mapped to Word-compatible extensions for the filename fallback.
_CONTENT_TYPE_EXTENSIONS = {
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-word": ".doc",
}

_RESERVED_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def sanitise_name(name: str, *, fallback: str = "untitled") -> str:
    """Return a filesystem-safe version of a single path segment.

    Removes path separators, control/null characters, and OS-invalid
    characters; collapses whitespace; avoids ``.``/``..`` and reserved device
    names; strips trailing spaces and dots; and enforces a maximum length.
    """
    if name is None:
        name = ""

    # Replace path separators explicitly so a title like ``a/b`` becomes ``a-b``
    # rather than silently losing a segment.
    name = name.replace("/", "-").replace("\\", "-")
    name = _INVALID_CHARS.sub("", name)
    # Collapse runs of whitespace into a single space.
    name = re.sub(r"\s+", " ", name).strip()
    # Windows forbids trailing spaces and dots.
    name = name.rstrip(" .")

    if not name or name in {".", ".."}:
        return fallback

    if name.lower() in _RESERVED_NAMES:
        name = f"{name}_"

    if len(name) > MAX_NAME_LENGTH:
        name = name[:MAX_NAME_LENGTH].rstrip(" .")

    return name or fallback


def split_extension(filename: str) -> tuple[str, str]:
    """Split a filename into ``(stem, extension)`` where extension includes the dot."""
    stem, ext = os.path.splitext(filename)
    return stem, ext


def add_collision_suffix(name: str, page_id: str) -> str:
    """Append ``- <page_id>`` before any extension to disambiguate collisions."""
    stem, ext = split_extension(name)
    return f"{stem} - {page_id}{ext}"


def parse_content_disposition(header: str | None) -> str | None:
    """Extract a filename from a ``Content-Disposition`` header.

    Supports both ``filename=`` and RFC 5987 ``filename*=``. When both are
    present, ``filename*`` takes precedence. Returns ``None`` if no usable
    filename is found. The returned filename is not yet sanitised.
    """
    if not header:
        return None

    extended = _extended_filename(header)
    if extended:
        return extended

    match = re.search(r'filename\s*=\s*"([^"]*)"', header, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"filename\s*=\s*([^;]+)", header, flags=re.IGNORECASE)
    if match:
        value = match.group(1).strip().strip('"').strip()
        # Guard against a server sending path components.
        value = os.path.basename(value.replace("\\", "/"))
        return value or None

    return None


def _extended_filename(header: str) -> str | None:
    match = re.search(r"filename\*\s*=\s*([^;]+)", header, flags=re.IGNORECASE)
    if not match:
        return None

    value = match.group(1).strip()
    # Form: charset'lang'percent-encoded-value
    charset = "utf-8"
    encoded = value
    if "'" in value:
        parts = value.split("'", 2)
        if len(parts) == 3:
            charset = parts[0] or "utf-8"
            encoded = parts[2]

    try:
        decoded = unquote(encoded, encoding=charset, errors="strict")
    except (LookupError, UnicodeDecodeError):
        decoded = unquote(encoded, errors="replace")

    decoded = os.path.basename(decoded.replace("\\", "/")).strip()
    return decoded or None


def extension_for_content_type(content_type: str | None) -> str | None:
    """Return a Word extension for a content type, or ``None`` if unknown."""
    if not content_type:
        return None
    main = content_type.split(";", 1)[0].strip().lower()
    return _CONTENT_TYPE_EXTENSIONS.get(main)
