"""Extract embedded images from a Word export and rewrite references.

Word exports reference images by a bare hash (the basename of each part's
``Content-Location``, e.g. ``file:///C:/<hash>``) and mark every part as
``application/octet-stream``. So we resolve ``<img>`` sources against the parts,
sniff the real image type from magic bytes, write each referenced image into a
per-document ``*.assets/`` folder, and rewrite the ``src`` to a relative link.
"""

from __future__ import annotations

from pathlib import Path
from posixpath import join as posix_join

from bs4 import BeautifulSoup

from word_to_markdown.mhtml import ImagePart, MhtmlDocument

# content-type -> extension for the cases magic sniffing cannot cover.
_CONTENT_TYPE_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
}


def extract_assets(
    doc: MhtmlDocument, assets_dir: Path, assets_rel: str
) -> tuple[str, int]:
    """Write referenced images and return ``(rewritten_html, count)``.

    ``assets_dir`` is where image files are written; ``assets_rel`` is the path
    (relative to the Markdown file) used inside the rewritten ``src`` links.
    Only images actually referenced by an ``<img>`` tag are written.
    """
    if not doc.images:
        return doc.html, 0

    lookup = _build_lookup(doc.images)
    soup = BeautifulSoup(doc.html, "html.parser")

    assigned: dict[int, str] = {}  # id(part) -> filename
    written = 0

    for img in soup.find_all("img"):
        src = img.get("src")
        part = _resolve(src, lookup)
        if part is None:
            continue

        key = id(part)
        filename = assigned.get(key)
        if filename is None:
            filename = _unique_filename(
                _base_name(part, src), _sniff_ext(part), assigned.values()
            )
            assets_dir.mkdir(parents=True, exist_ok=True)
            (assets_dir / filename).write_bytes(part.data)
            assigned[key] = filename
            written += 1

        img["src"] = posix_join(assets_rel, filename)

    return str(soup), written


def _build_lookup(images: list[ImagePart]) -> dict[str, ImagePart]:
    """Map every plausible reference key to its part."""
    lookup: dict[str, ImagePart] = {}
    for part in images:
        for key in _reference_keys(part):
            lookup.setdefault(key, part)
    return lookup


def _reference_keys(part: ImagePart) -> list[str]:
    keys: list[str] = []
    if part.content_id:
        keys.append(part.content_id)
    if part.content_location:
        loc = part.content_location
        keys.append(loc)
        keys.append(loc.rsplit("/", 1)[-1])  # bare basename (the hash)
    return keys


def _resolve(src: str | None, lookup: dict[str, ImagePart]) -> ImagePart | None:
    if not src:
        return None
    candidate = src.strip()
    if candidate.startswith("cid:"):
        candidate = candidate[4:]
    for key in (candidate, candidate.rsplit("/", 1)[-1]):
        part = lookup.get(key)
        if part is not None:
            return part
    return None


def _base_name(part: ImagePart, src: str | None) -> str:
    """A stable stem for the embedded image, derived from its reference."""
    if part.content_location:
        stem = part.content_location.rsplit("/", 1)[-1]
    elif part.content_id:
        stem = part.content_id
    elif src:
        stem = src.strip().rsplit("/", 1)[-1]
    else:
        stem = "image"
    stem = "".join(ch for ch in stem if ch.isalnum() or ch in "-_.")
    # Long Confluence hashes are unwieldy; keep them short but still unique.
    return (stem or "image")[:40]


def _unique_filename(stem: str, ext: str, taken) -> str:
    taken = set(taken)
    candidate = f"{stem}{ext}"
    counter = 1
    while candidate in taken:
        candidate = f"{stem}-{counter}{ext}"
        counter += 1
    return candidate


def _sniff_ext(part: ImagePart) -> str:
    """Determine an image extension from magic bytes, then content-type."""
    data = part.data
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:2] == b"BM":
        return ".bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:5] == b"<?xml" or data[:4] == b"<svg":
        return ".svg"
    return _CONTENT_TYPE_EXT.get(part.content_type.lower(), ".bin")
