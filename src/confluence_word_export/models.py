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
    """The outcome of applying title filters to a page."""

    included: bool
    reason: str
    excluded_by_term: bool = False
    """True when excluded by an explicit exclude/ignore term (not an include miss).

    Term exclusions prune the whole subtree; include misses do not.
    """


# Download status values used in reporting and :class:`DownloadResult`.
STATUS_DOWNLOADED = "DOWNLOADED"
STATUS_SKIPPED = "SKIPPED"
STATUS_EXCLUDED = "EXCLUDED"
STATUS_FAILED = "FAILED"


@dataclass(frozen=True)
class DownloadResult:
    """The result of attempting to download one page's Word export."""

    page: Page
    status: str
    path: Path | None
    error: str | None
