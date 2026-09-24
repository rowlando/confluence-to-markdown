"""Parsing and validation of Confluence Cloud page URLs."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from confluence_word_export.errors import UsageError

# Matches ``/wiki/spaces/<KEY>/pages/<id>/...`` and ``/wiki/pages/<id>`` styles,
# capturing the numeric page ID.
_PAGE_ID_PATTERNS = (
    re.compile(r"/wiki/spaces/[^/]+/pages/(\d+)(?:/|$)"),
    re.compile(r"/wiki/pages/(\d+)(?:/|$)"),
    re.compile(r"/wiki/pages/viewpage\.action$"),  # query-string form, handled below
)

_ALLOWED_HOST_SUFFIX = ".atlassian.net"


def parse_page_url(url: str) -> tuple[str, str]:
    """Return ``(site_url, page_id)`` extracted from a Confluence page URL.

    The site URL is the scheme + host (e.g. ``https://example.atlassian.net``).

    Raises :class:`UsageError` for URLs that are not HTTPS, lack a numeric page
    ID, are space-home URLs, or target an unsupported host.
    """
    if not isinstance(url, str) or not url.strip():
        raise UsageError("A Confluence page URL is required.")

    parts = urlsplit(url.strip())

    if parts.scheme != "https":
        raise UsageError(f"URL must use HTTPS: {url!r}")

    host = parts.netloc
    if not host:
        raise UsageError(f"Malformed URL (no host): {url!r}")

    if not host.endswith(_ALLOWED_HOST_SUFFIX):
        raise UsageError(
            f"Unsupported host {host!r}. Only Confluence Cloud "
            f"(*{_ALLOWED_HOST_SUFFIX}) URLs are supported."
        )

    page_id = _extract_page_id(parts.path, parts.query)
    if page_id is None:
        raise UsageError(
            f"Could not find a Confluence page ID in the URL: {url!r}. "
            "Provide a page URL such as "
            "https://your-site.atlassian.net/wiki/spaces/KEY/pages/12345/Title"
        )

    site_url = f"{parts.scheme}://{host}"
    return site_url, page_id


def _extract_page_id(path: str, query: str) -> str | None:
    for pattern in _PAGE_ID_PATTERNS[:2]:
        match = pattern.search(path)
        if match:
            return match.group(1)

    # ``viewpage.action?pageId=12345`` legacy form.
    if path.endswith("/wiki/pages/viewpage.action"):
        for pair in query.split("&"):
            key, _, value = pair.partition("=")
            if key == "pageId" and value.isdigit():
                return value

    return None
