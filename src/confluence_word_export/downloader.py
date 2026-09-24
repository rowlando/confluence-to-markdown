"""Word export download, validation, and atomic saving."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import requests

from confluence_word_export.errors import AuthError
from confluence_word_export.filenames import (
    add_collision_suffix,
    extension_for_content_type,
    parse_content_disposition,
    sanitise_name,
    split_extension,
)
from confluence_word_export.hierarchy import PlacedPage
from confluence_word_export.models import (
    STATUS_DOWNLOADED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    Auth,
    DownloadResult,
)

DEFAULT_TIMEOUT = (10, 120)  # (connect, read) seconds
# Responses smaller than this are almost certainly not a real Word document.
MIN_WORD_BYTES = 100
_HTML_SNIFF_LEN = 512


class InvalidWordResponse(Exception):
    """Raised when a download does not look like a genuine Word export."""


class Downloader:
    """Downloads Word exports for individual pages."""

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
        self._allowed_host = urlsplit(self.site_url).netloc
        # Paths claimed during this run, mapping resolved path -> page id, used to
        # disambiguate different sibling pages that share a server filename.
        self._claimed: dict[Path, str] = {}
        if session is None:
            from confluence_word_export.auth import build_session

            session = build_session(auth)
        self.session = session

    def download(self, placed: PlacedPage, *, overwrite: bool) -> DownloadResult:
        """Download, validate, name, and atomically save one Word export."""
        page = placed.page
        target_dir = placed.parent_dir
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return DownloadResult(
                page, STATUS_FAILED, None, f"cannot create {target_dir}: {exc}"
            )

        url = f"{self.site_url}/wiki/exportword"
        try:
            response = self.session.get(
                url,
                params={"pageId": page.id},
                timeout=self.timeout,
                allow_redirects=True,
                stream=True,
            )
        except requests.RequestException as exc:
            return DownloadResult(page, STATUS_FAILED, None, f"request error: {exc}")

        with response:
            self._check_redirect_host(response)

            if response.status_code in (401, 403):
                # Invalid credentials should abort the whole run.
                raise AuthError(
                    f"Word export authorisation failed (HTTP {response.status_code}) "
                    f"for page {page.id}."
                )
            if response.status_code >= 400:
                return DownloadResult(
                    page, STATUS_FAILED, None, f"HTTP {response.status_code}"
                )

            content_type = response.headers.get("Content-Type")
            disposition = response.headers.get("Content-Disposition")

            filename = self._resolve_filename(page, disposition, content_type)
            target_path = self._resolve_target_path(target_dir, filename, page.id)
            self._claimed[target_path] = page.id

            if target_path.exists() and not overwrite:
                return DownloadResult(page, STATUS_SKIPPED, target_path, None)

            try:
                self._stream_to_file(response, target_path)
            except InvalidWordResponse as exc:
                return DownloadResult(page, STATUS_FAILED, None, str(exc))
            except OSError as exc:
                return DownloadResult(page, STATUS_FAILED, None, f"write error: {exc}")

        return DownloadResult(page, STATUS_DOWNLOADED, target_path, None)

    # -- Internals --------------------------------------------------------

    def _check_redirect_host(self, response: requests.Response) -> None:
        """Ensure credentials were not followed to an unrelated host."""
        for hop in list(response.history) + [response]:
            host = urlsplit(hop.url).netloc
            if host and host != self._allowed_host:
                raise AuthError(
                    f"Refusing response: redirect left the expected host "
                    f"({self._allowed_host} -> {host})."
                )

    def _resolve_filename(
        self, page, disposition: str | None, content_type: str | None
    ) -> str:
        server_name = parse_content_disposition(disposition)
        if server_name:
            stem, ext = split_extension(server_name)
            safe_stem = sanitise_name(stem, fallback=sanitise_name(page.title))
            safe_ext = _sanitise_extension(ext)
            if not safe_ext:
                safe_ext = extension_for_content_type(content_type) or ".doc"
            return f"{safe_stem}{safe_ext}"

        # Fallback: page title + inferred extension (PRD 13.2).
        ext = extension_for_content_type(content_type) or ".doc"
        return f"{sanitise_name(page.title)}{ext}"

    def _resolve_target_path(
        self, target_dir: Path, filename: str, page_id: str
    ) -> Path:
        """Return a safe, collision-free path inside ``target_dir``.

        ``filename`` has already been sanitised; taking the basename here is a
        final defence against path traversal from a server-provided name.

        A page-ID suffix is only applied when the path was already claimed in
        this run by a *different* page (two siblings sharing a server filename).
        An existing file from a previous run keeps its plain name so it is
        correctly reported as skipped.
        """
        stem, ext = split_extension(os.path.basename(filename))
        base = f"{sanitise_name(stem, fallback=f'page-{page_id}')}{ext}"
        candidate = target_dir / base

        while candidate in self._claimed and self._claimed[candidate] != page_id:
            base = add_collision_suffix(base, page_id)
            candidate = target_dir / base
        return candidate

    def _stream_to_file(self, response: requests.Response, target_path: Path) -> None:
        target_dir = target_path.parent
        first_chunk = b""
        fd, tmp_name = tempfile.mkstemp(
            dir=str(target_dir), suffix=".part", prefix="." + target_path.name + "."
        )
        tmp_path = Path(tmp_name)
        total = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    if not first_chunk:
                        first_chunk = chunk[:_HTML_SNIFF_LEN]
                        _reject_non_word(response, first_chunk)
                    handle.write(chunk)
                    total += len(chunk)
            if total < MIN_WORD_BYTES:
                raise InvalidWordResponse(
                    f"response too small to be a Word document ({total} bytes)"
                )
            os.replace(tmp_path, target_path)
        except BaseException:
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            raise


def _sanitise_extension(ext: str) -> str:
    """Return a safe extension (leading dot + alphanumerics) or empty string."""
    if not ext:
        return ""
    cleaned = "." + "".join(ch for ch in ext[1:] if ch.isalnum())
    return cleaned if len(cleaned) > 1 else ""


def _reject_non_word(response: requests.Response, head: bytes) -> None:
    content_type = (response.headers.get("Content-Type") or "").lower()
    if "text/html" in content_type or "application/json" in content_type:
        raise InvalidWordResponse(
            f"unexpected content type {content_type!r} (likely a login or error page)"
        )

    sniff = head.lstrip().lower()
    if sniff.startswith((b"<!doctype", b"<html", b"<?xml", b"{")):
        raise InvalidWordResponse(
            "response body looks like HTML/JSON, not a Word document"
        )
