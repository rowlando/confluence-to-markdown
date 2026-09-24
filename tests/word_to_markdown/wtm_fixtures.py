"""Shared helpers for word_to_markdown tests."""

from __future__ import annotations

import base64
import quopri

from word_to_markdown.backends import Backend

# A minimal 1x1 PNG.
PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def make_mhtml(html: str, images: list[tuple[str, bytes, str]] | None = None) -> bytes:
    """Build MHTML bytes mimicking a Confluence 'Export to Word' .doc.

    ``images`` is a list of ``(content_location, data, content_type)`` tuples.
    The HTML part is quoted-printable encoded and images are base64 encoded, as
    Confluence emits them.
    """
    images = images or []
    boundary = "=_Part_TEST_123"
    sep = f"--{boundary}"

    chunks = [
        f"MIME-Version: 1.0\r\n"
        f'Content-Type: multipart/related; boundary="{boundary}"\r\n\r\n'
    ]

    html_headers = (
        "Content-Type: text/html; charset=UTF-8\r\n"
        "Content-Transfer-Encoding: quoted-printable\r\n"
        "Content-Location: file:///C:/exported.html\r\n\r\n"
    )
    html_body = quopri.encodestring(html.encode("utf-8")).decode("ascii")
    chunks.append(f"{sep}\r\n{html_headers}{html_body}\r\n")

    for location, data, content_type in images:
        img_headers = (
            f"Content-Type: {content_type}\r\n"
            "Content-Transfer-Encoding: base64\r\n"
            f"Content-Location: {location}\r\n\r\n"
        )
        img_body = base64.encodebytes(data).decode("ascii")
        chunks.append(f"{sep}\r\n{img_headers}{img_body}\r\n")

    chunks.append(f"{sep}--\r\n")
    return "".join(chunks).encode("utf-8")


class FakeBackend(Backend):
    """Deterministic backend for testing the conversion pipeline."""

    name = "fake"

    def __init__(self) -> None:
        self.html_calls: list[str] = []
        self.file_calls: list[str] = []

    def convert_html(self, html: str, source_name: str) -> str:
        self.html_calls.append(html)
        return f"# from-html\n\n{html}"

    def convert_file(self, path) -> str:
        self.file_calls.append(str(path))
        return f"# from-file {path.name}"
