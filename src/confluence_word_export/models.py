"""Core data models for the Confluence Word Export tool."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Auth:
    """HTTP Basic authentication credentials for Confluence Cloud.

    Credentials are read from environment variables and must never be logged,
    printed, or written to disk.
    """

    email: str
    api_token: str

    def as_basic_auth(self) -> tuple[str, str]:
        """Return the ``(username, password)`` tuple for ``requests`` Basic auth."""
        return (self.email, self.api_token)

    def __repr__(self) -> str:  # pragma: no cover - defensive credential hiding
        return f"Auth(email={self.email!r}, api_token='***')"


@dataclass(frozen=True)
class Page:
    """Metadata for a single Confluence page."""

    id: str
    title: str
    parent_id: str | None
    depth: int
    child_position: int | None


@dataclass(frozen=True)
class FilterDecision:
    """The outcome of applying title filters to a page.

    Exactly one of :attr:`selected`, :attr:`excluded` and :attr:`unselected`
    holds for any decision.
    """

    selected: bool
    """True when the page will be downloaded."""
    reason: str
    excluded: bool = False
    """True when removed by an exclude term, directly or via an ancestor.

    Exclusion removes the page's whole subtree.
    """

    @property
    def unselected(self) -> bool:
        """True when no include term matched; descendants are unaffected."""
        return not self.selected and not self.excluded


# Download status values used in reporting and :class:`DownloadResult`.
STATUS_DOWNLOADED = "DOWNLOADED"
STATUS_SKIPPED = "SKIPPED"
STATUS_EXCLUDED = "EXCLUDED"
"""Removed by an exclude term, together with its whole subtree."""
STATUS_UNSELECTED = "UNSELECTED"
"""Not matched by any include term; selected descendants are still downloaded."""
STATUS_FAILED = "FAILED"


@dataclass(frozen=True)
class DownloadResult:
    """The result of attempting to download one page's Word export."""

    page: Page
    status: str
    path: Path | None
    error: str | None
