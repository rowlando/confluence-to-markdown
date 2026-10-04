"""Convert a single input file to a Markdown file.

Decides how to handle each input:

* MHTML ``.doc`` (Word export) -> parse, extract embedded images into a sibling
  ``*.assets/`` folder, rewrite links, then run the backend on the clean HTML.
* Real ``.docx`` / binary ``.doc`` -> hand the file straight to the backend.
* ``.html`` / ``.htm`` -> run the backend on the file's HTML directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from word_to_markdown.assets import extract_assets
from word_to_markdown.backends import Backend
from word_to_markdown.mhtml import is_mhtml, parse_mhtml

# Statuses for a single-file conversion.
STATUS_CONVERTED = "converted"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class ConversionResult:
    source: Path
    output: Path
    status: str
    images: int = 0
    error: str | None = None


def convert_file(
    source: Path,
    output: Path,
    backend: Backend,
    *,
    overwrite: bool,
) -> ConversionResult:
    """Convert ``source`` to Markdown at ``output`` using ``backend``."""
    if output.exists() and not overwrite:
        return ConversionResult(source, output, STATUS_SKIPPED)

    try:
        markdown, images = _render(source, output, backend)
    except Exception as exc:  # noqa: BLE001 - report, keep processing others
        return ConversionResult(source, output, STATUS_FAILED, error=str(exc))

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(markdown, encoding="utf-8")
    except OSError as exc:
        return ConversionResult(
            source, output, STATUS_FAILED, error=f"write error: {exc}"
        )

    return ConversionResult(source, output, STATUS_CONVERTED, images=images)


def _render(source: Path, output: Path, backend: Backend) -> tuple[str, int]:
    suffix = source.suffix.lower()

    if suffix in (".doc", ".html", ".htm") and is_mhtml(source):
        doc = parse_mhtml(source)
        assets_dir, assets_rel = _assets_target(output)
        html, images = extract_assets(doc, assets_dir, assets_rel)
        return backend.convert_html(html, source.name), images

    if suffix in (".html", ".htm"):
        html = source.read_text(encoding="utf-8", errors="replace")
        return backend.convert_html(html, source.name), 0

    # Genuine binary Word document (.docx or legacy .doc): let the backend read
    # it directly.
    return backend.convert_file(source), 0


def _assets_target(output: Path) -> tuple[Path, str]:
    """Return the embedded-image directory and its path relative to the Markdown file."""
    rel = f"{output.stem}.assets"
    return output.parent / rel, rel
