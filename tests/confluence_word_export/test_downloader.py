import pytest

from confluence_word_export.downloader import Downloader
from confluence_word_export.errors import AuthError
from confluence_word_export.hierarchy import build_hierarchy
from confluence_word_export.models import (
    STATUS_DOWNLOADED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    Auth,
    Page,
)

AUTH = Auth("a@b.com", "tok")
SITE = "https://x.atlassian.net"
# A minimal OLE/DOC-ish body large enough to pass the size check.
WORD_BODY = b"\xd0\xcf\x11\xe0" + b"\x00" * 200


class FakeStreamResponse:
    def __init__(
        self,
        status=200,
        headers=None,
        body=b"",
        history=None,
        url=SITE + "/wiki/exportword",
    ):
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self.history = history or []
        self.url = url

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def get(
        self, url, params=None, timeout=None, allow_redirects=True, stream=False, **kw
    ):
        self.calls.append((url, params))
        return self._response


def placed_for(pid, title, tmp_path):
    root = Page("100", "Root", None, 0, None)
    child = Page(pid, title, "100", 1, 0)
    placed = build_hierarchy(root, [child], tmp_path)
    return placed[pid]


class TestDownloader:
    def test_successful_download_uses_server_filename(self, tmp_path):
        resp = FakeStreamResponse(
            headers={
                "Content-Type": "application/msword",
                "Content-Disposition": 'attachment; filename="Authentication guidance.doc"',
            },
            body=WORD_BODY,
        )
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        result = d.download(placed, overwrite=False)
        assert result.status == STATUS_DOWNLOADED
        assert result.path.name == "Authentication guidance.doc"
        assert result.path.exists()
        assert result.path.read_bytes() == WORD_BODY

    def test_rejects_html_login(self, tmp_path):
        resp = FakeStreamResponse(
            headers={"Content-Type": "text/html"},
            body=b"<!DOCTYPE html><html><body>login</body></html>" + b" " * 200,
        )
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        result = d.download(placed, overwrite=False)
        assert result.status == STATUS_FAILED
        # No .part or final file left behind.
        assert list(placed.parent_dir.glob("*")) == []

    def test_skips_existing(self, tmp_path):
        resp = FakeStreamResponse(
            headers={
                "Content-Type": "application/msword",
                "Content-Disposition": 'attachment; filename="Authentication.doc"',
            },
            body=WORD_BODY,
        )
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        placed.parent_dir.mkdir(parents=True, exist_ok=True)
        (placed.parent_dir / "Authentication.doc").write_bytes(b"existing")
        result = d.download(placed, overwrite=False)
        assert result.status == STATUS_SKIPPED
        assert (placed.parent_dir / "Authentication.doc").read_bytes() == b"existing"

    def test_overwrite_replaces(self, tmp_path):
        resp = FakeStreamResponse(
            headers={
                "Content-Type": "application/msword",
                "Content-Disposition": 'attachment; filename="Authentication.doc"',
            },
            body=WORD_BODY,
        )
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        placed.parent_dir.mkdir(parents=True, exist_ok=True)
        (placed.parent_dir / "Authentication.doc").write_bytes(b"old")
        result = d.download(placed, overwrite=True)
        assert result.status == STATUS_DOWNLOADED
        assert result.path.read_bytes() == WORD_BODY

    def test_fallback_filename_from_title(self, tmp_path):
        resp = FakeStreamResponse(
            headers={"Content-Type": "application/msword"},
            body=WORD_BODY,
        )
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        result = d.download(placed, overwrite=False)
        assert result.status == STATUS_DOWNLOADED
        assert result.path.name == "Authentication.doc"

    def test_401_raises_auth_error(self, tmp_path):
        resp = FakeStreamResponse(status=401)
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        with pytest.raises(AuthError):
            d.download(placed, overwrite=False)

    def test_redirect_to_other_host_rejected(self, tmp_path):
        hop = FakeStreamResponse(url="https://evil.example.com/login")
        resp = FakeStreamResponse(
            headers={"Content-Type": "application/msword"},
            body=WORD_BODY,
            history=[hop],
        )
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        with pytest.raises(AuthError):
            d.download(placed, overwrite=False)

    def test_too_small_response_fails(self, tmp_path):
        resp = FakeStreamResponse(
            headers={
                "Content-Type": "application/msword",
                "Content-Disposition": 'attachment; filename="tiny.doc"',
            },
            body=b"\xd0\xcf\x11\xe0",  # under MIN_WORD_BYTES
        )
        d = Downloader(SITE, AUTH, session=FakeSession(resp))
        placed = placed_for("222", "Authentication", tmp_path)
        result = d.download(placed, overwrite=False)
        assert result.status == STATUS_FAILED
        assert list(placed.parent_dir.glob("*")) == []

    def test_sibling_same_server_filename_disambiguated(self, tmp_path):
        root = Page("100", "Root", None, 0, None)
        a = Page("201", "Alpha", "100", 1, 0)
        b = Page("202", "Beta", "100", 1, 1)
        placed = build_hierarchy(root, [a, b], tmp_path)

        headers = {
            "Content-Type": "application/msword",
            "Content-Disposition": 'attachment; filename="Guidance.doc"',
        }
        d = Downloader(
            SITE,
            AUTH,
            session=FakeSession(FakeStreamResponse(headers=headers, body=WORD_BODY)),
        )

        r1 = d.download(placed["201"], overwrite=False)
        r2 = d.download(placed["202"], overwrite=False)
        assert r1.status == STATUS_DOWNLOADED
        assert r2.status == STATUS_DOWNLOADED
        assert r1.path != r2.path
        assert r1.path.name == "Guidance.doc"
        assert r2.path.name == "Guidance - 202.doc"
