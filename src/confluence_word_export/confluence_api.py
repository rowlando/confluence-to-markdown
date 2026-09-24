"""Confluence Cloud REST API client (v2).

Only the endpoints needed for discovery are implemented:

* ``GET /wiki/api/v2/pages/{id}`` for root-page metadata;
* ``GET /wiki/api/v2/pages/{id}/descendants`` for descendant discovery.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urljoin

import requests

from confluence_word_export.errors import (
    TLS_HINT,
    AuthError,
    RootDiscoveryError,
    UsageError,
)
from confluence_word_export.models import Auth, Page

DEFAULT_TIMEOUT = (10, 60)  # (connect, read) seconds
DESCENDANTS_PAGE_LIMIT = 250
# The API caps depth; request the documented maximum to obtain all descendants.
MAX_DESCENDANT_DEPTH = 5


class ConfluenceClient:
    """Thin wrapper around the Confluence v2 REST API."""

    def __init__(
        self,
        site_url: str,
        auth: Auth,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self.site_url = site_url.rstrip("/")
        self.auth = auth
        self.timeout = timeout
        if session is None:
            from confluence_word_export.auth import build_session

            session = build_session(auth)
        self.session = session

    # -- HTTP helpers -----------------------------------------------------

    def _get_json(
        self, path_or_url: str, *, params: dict[str, Any] | None = None
    ) -> dict:
        if path_or_url.startswith("http"):
            url = path_or_url
        else:
            url = urljoin(self.site_url + "/", path_or_url.lstrip("/"))

        try:
            response = self.session.get(
                url, params=params, timeout=self.timeout, allow_redirects=True
            )
        except requests.exceptions.SSLError as exc:
            raise RootDiscoveryError(
                f"Could not reach Confluence at {self.site_url}: {exc}\n\n{TLS_HINT}"
            ) from exc
        except requests.RequestException as exc:
            raise RootDiscoveryError(
                f"Could not reach Confluence at {self.site_url}: {exc}"
            ) from exc

        _raise_for_status(response)

        try:
            return response.json()
        except ValueError as exc:
            raise RootDiscoveryError(
                f"Confluence returned a non-JSON response for {url}."
            ) from exc

    # -- Public API -------------------------------------------------------

    def get_page(self, page_id: str) -> Page:
        """Retrieve metadata for a single page.

        Raises :class:`RootDiscoveryError` if the page cannot be retrieved or is
        not a page.
        """
        if not page_id.isdigit():
            raise UsageError(f"Invalid page ID: {page_id!r}")

        data = self._get_json(f"/wiki/api/v2/pages/{page_id}")
        page = _page_from_json(data, depth=0)
        if page is None:
            raise RootDiscoveryError(f"Content {page_id} is not a Confluence page.")
        return page

    def get_descendant_pages(self, root_page_id: str) -> list[Page]:
        """Return all descendant pages, following cursor-based pagination.

        Only descendants of type ``page`` are returned.
        """
        results: list[Page] = []
        path: str | None = f"/wiki/api/v2/pages/{root_page_id}/descendants"
        params: dict[str, Any] | None = {
            "limit": DESCENDANTS_PAGE_LIMIT,
            "depth": MAX_DESCENDANT_DEPTH,
        }

        while path is not None:
            data = self._get_json(path, params=params)
            for item in data.get("results", []):
                page = _page_from_json(item, depth=item.get("depth"))
                if page is not None:
                    results.append(page)

            path = _next_link(data)
            # The cursor link already carries all query parameters.
            params = None

        return results


def _raise_for_status(response: requests.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    if status in (401,):
        raise AuthError(
            "Authentication failed (HTTP 401). Check CONFLUENCE_EMAIL and "
            "CONFLUENCE_API_TOKEN."
        )
    if status in (403,):
        raise AuthError(
            "Access denied (HTTP 403). The account lacks permission for this content."
        )
    if status == 404:
        raise RootDiscoveryError(
            "Content not found (HTTP 404). Check the page URL and your access."
        )
    raise RootDiscoveryError(
        f"Confluence request failed with HTTP {status} for {response.url}."
    )


def _page_from_json(data: dict, depth: int | None) -> Page | None:
    """Map an API item to :class:`Page`, or ``None`` if it is not a page."""
    item_type = data.get("type")
    # The single-page endpoint has no ``type`` field but is always a page.
    if item_type is not None and item_type != "page":
        return None

    page_id = data.get("id")
    if page_id is None:
        return None

    parent_id = data.get("parentId")
    return Page(
        id=str(page_id),
        title=data.get("title") or f"Untitled {page_id}",
        parent_id=str(parent_id) if parent_id is not None else None,
        depth=int(depth) if depth is not None else 0,
        child_position=_coerce_int(data.get("childPosition")),
    )


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _next_link(data: dict) -> str | None:
    links = data.get("_links") or {}
    nxt = links.get("next")
    if not nxt:
        return None
    return nxt
