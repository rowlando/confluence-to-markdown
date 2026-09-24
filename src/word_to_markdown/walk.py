"""Discover input documents and map them to mirrored Markdown output paths."""

from __future__ import annotations

import re
from pathlib import Path

# Input file types we know how to convert.
INPUT_EXTENSIONS = (".doc", ".docx", ".html", ".htm")

_MULTISPACE = re.compile(r"\s+")


def find_inputs(root: Path) -> list[Path]:
    """Return a sorted list of convertible files beneath ``root``."""
    return sorted(
        p
        for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in INPUT_EXTENSIONS
    )


def output_path_for(
    source: Path,
    input_root: Path,
    output_root: Path,
    *,
    flatten: bool = False,
    clean_names: bool = False,
) -> Path:
    """Map ``source`` to its Markdown output path under ``output_root``.

    Mirrors the relative directory structure by default. ``flatten`` drops the
    subdirectories; ``clean_names`` turns Confluence ``+``-encoded names into
    ordinary spaced names.
    """
    rel = source.relative_to(input_root)
    parts = [rel.name] if flatten else list(rel.parts)

    parts[-1] = Path(parts[-1]).stem + ".md"
    if clean_names:
        parts = [_clean_segment(seg) for seg in parts]

    return output_root.joinpath(*parts)


def _clean_segment(segment: str) -> str:
    """Turn a Confluence ``+``-encoded name into a readable spaced name."""
    suffix = ""
    if segment.endswith(".md"):
        segment, suffix = segment[:-3], ".md"
    cleaned = segment.replace("+", " ")
    cleaned = _MULTISPACE.sub(" ", cleaned).strip()
    return (cleaned or "untitled") + suffix
