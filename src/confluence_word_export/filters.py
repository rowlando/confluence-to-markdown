"""Title-based filtering and ignore-file loading."""

from __future__ import annotations

from pathlib import Path

from confluence_word_export.errors import UsageError
from confluence_word_export.models import FilterDecision, Page


def load_ignore_terms(path: Path | None, *, explicit: bool) -> list[str]:
    """Load literal, case-insensitive exclude terms from an ignore file.

    ``explicit`` indicates the user supplied ``--ignore-file`` on the command
    line. When ``explicit`` is True and the file is missing or unreadable, a
    :class:`UsageError` is raised. When False (the default path), a missing file
    is silently ignored.

    Blank lines and lines whose first non-whitespace character is ``#`` are
    skipped. Whitespace is trimmed and duplicates are removed while preserving
    order.
    """
    if path is None:
        return []

    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        if explicit:
            raise UsageError(f"Ignore file not found: {path}") from exc
        return []
    except OSError as exc:
        if explicit:
            raise UsageError(f"Could not read ignore file {path}: {exc}") from exc
        return []

    terms: list[str] = []
    seen: set[str] = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key = stripped.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(key)
    return terms


def _normalise_terms(terms: list[str]) -> list[str]:
    """Trim, lowercase, drop empties, and de-duplicate filter terms."""
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        cleaned = term.strip().lower()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def decide(
    title: str,
    include_terms: list[str],
    exclude_terms: list[str],
) -> FilterDecision:
    """Return the filter decision for a single title.

    Rules (PRD section 10):

    * matching is case-insensitive literal substring;
    * a page is excluded if its title contains any exclude term;
    * otherwise it is selected if there are no include terms, or its title
      contains at least one include term (OR semantics);
    * otherwise it is unselected.
    """
    lowered = title.lower()

    for term in exclude_terms:
        if term in lowered:
            return FilterDecision(
                selected=False, reason=f"excluded by {term!r}", excluded=True
            )

    if not include_terms:
        return FilterDecision(selected=True, reason="no include filters")

    for term in include_terms:
        if term in lowered:
            return FilterDecision(selected=True, reason=f"matched include {term!r}")

    return FilterDecision(selected=False, reason="no include term matched")


def build_decisions(
    pages: list[Page],
    include_terms: list[str],
    exclude_terms: list[str],
) -> dict[str, FilterDecision]:
    """Return a mapping of page ID to :class:`FilterDecision`.

    A page excluded by an exclude term (from ``--exclude`` or the ignore file)
    takes its entire subtree with it: every descendant is excluded too, so a
    section such as "Archived" is left out in full and no directory is created
    for it. An unselected page (an include miss) does *not* affect its
    subtree: its descendants may still be selected.
    """
    includes = _normalise_terms(include_terms)
    excludes = _normalise_terms(exclude_terms)
    decisions = {page.id: decide(page.title, includes, excludes) for page in pages}

    by_id = {page.id: page for page in pages}
    for page in pages:
        if decisions[page.id].excluded:
            continue
        ancestor_id = page.parent_id
        while ancestor_id is not None and ancestor_id in by_id:
            ancestor = decisions[ancestor_id]
            if ancestor.excluded:
                decisions[page.id] = FilterDecision(
                    selected=False,
                    reason=f"ancestor excluded ({by_id[ancestor_id].title!r})",
                    excluded=True,
                )
                break
            ancestor_id = by_id[ancestor_id].parent_id

    return decisions


def select_pages(
    pages: list[Page],
    include_terms: list[str],
    exclude_terms: list[str],
) -> list[Page]:
    """Return only the selected pages."""
    decisions = build_decisions(pages, include_terms, exclude_terms)
    return [page for page in pages if decisions[page.id].selected]
