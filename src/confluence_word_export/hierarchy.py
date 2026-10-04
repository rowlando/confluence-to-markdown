"""Reconstruct the Confluence hierarchy as local directory paths.

Hierarchy is built from page IDs and parent IDs only, never from titles or URL
structure (PRD section 12.4). A page that has children is represented as both a
Word export and a directory sharing the same base name. Directories for
unselected pages (an include-term miss) are still created so any selected
descendants keep their correct location; a page excluded by an exclude term
prunes its whole subtree, so no directory is created for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from confluence_word_export.filenames import add_collision_suffix, sanitise_name
from confluence_word_export.models import Page


@dataclass(frozen=True)
class PlacedPage:
    """A page positioned within the local output tree."""

    page: Page
    base_name: str
    """Collision-resolved, sanitised segment derived from the page title."""
    parent_dir: Path
    """Directory in which this page's Word export is written."""
    dir_path: Path
    """Directory representing this page's children (``parent_dir / base_name``)."""
    has_children: bool


def build_hierarchy(
    root_page: Page,
    descendants: list[Page],
    output_directory: Path,
) -> dict[str, PlacedPage]:
    """Return a mapping of page ID to :class:`PlacedPage`.

    ``output_directory`` is the base directory. The root page becomes the
    top-level directory beneath it. The returned mapping includes the root page
    and every descendant.
    """
    output_directory = Path(output_directory)

    by_id: dict[str, Page] = {root_page.id: root_page}
    for page in descendants:
        by_id[page.id] = page

    # Group children by parent. Pages whose parent is unknown attach to the root
    # so nothing is lost.
    children: dict[str, list[Page]] = {}
    for page in descendants:
        parent = page.parent_id
        if parent is None or parent not in by_id or parent == page.id:
            parent = root_page.id
        children.setdefault(parent, []).append(page)

    has_children = {pid: bool(kids) for pid, kids in children.items()}

    placed: dict[str, PlacedPage] = {}

    root_base = _segment_names([root_page])[root_page.id]
    placed[root_page.id] = PlacedPage(
        page=root_page,
        base_name=root_base,
        parent_dir=output_directory,
        dir_path=output_directory / root_base,
        has_children=has_children.get(root_page.id, False),
    )

    # Breadth-first placement guarantees parents are placed before children.
    queue: list[str] = [root_page.id]
    while queue:
        parent_id = queue.pop(0)
        parent_placed = placed[parent_id]
        kids = children.get(parent_id, [])
        if not kids:
            continue

        segments = _segment_names(kids)
        for child in kids:
            base = segments[child.id]
            placed[child.id] = PlacedPage(
                page=child,
                base_name=base,
                parent_dir=parent_placed.dir_path,
                dir_path=parent_placed.dir_path / base,
                has_children=has_children.get(child.id, False),
            )
            queue.append(child.id)

    return placed


def _segment_names(siblings: list[Page]) -> dict[str, str]:
    """Return collision-resolved sanitised names for a set of sibling pages.

    Deterministic: siblings are ordered by ``(child_position, id)``; the first
    page to claim a sanitised name keeps it, and later colliding siblings get a
    page-ID suffix (PRD section 13.5).
    """
    ordered = sorted(
        siblings,
        key=lambda p: (
            p.child_position if p.child_position is not None else 1 << 30,
            _id_sort_key(p.id),
        ),
    )

    used: set[str] = set()
    result: dict[str, str] = {}
    for page in ordered:
        base = sanitise_name(page.title)
        candidate = base
        if candidate.lower() in used:
            candidate = add_collision_suffix(base, page.id)
        # Extremely defensive: if even the suffixed name collides, keep suffixing.
        while candidate.lower() in used:
            candidate = add_collision_suffix(candidate, page.id)
        used.add(candidate.lower())
        result[page.id] = candidate
    return result


def _id_sort_key(page_id: str) -> tuple[int, str]:
    return (0, page_id.zfill(24)) if page_id.isdigit() else (1, page_id)
