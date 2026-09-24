from pathlib import Path

from tests.word_to_markdown.wtm_fixtures import PNG_BYTES, make_mhtml
from word_to_markdown.mhtml import is_mhtml, parse_mhtml


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


class TestIsMhtml:
    def test_detects_confluence_export(self, tmp_path):
        path = _write(tmp_path, "doc.doc", make_mhtml("<html></html>"))
        assert is_mhtml(path) is True

    def test_plain_html_is_not_mhtml(self, tmp_path):
        path = _write(tmp_path, "page.html", b"<html><body>hi</body></html>")
        assert is_mhtml(path) is False

    def test_missing_file_is_not_mhtml(self, tmp_path):
        assert is_mhtml(tmp_path / "nope.doc") is False


class TestParseMhtml:
    def test_decodes_quoted_printable_html(self, tmp_path):
        html = "<html><body><p>a = b</p></body></html>"
        path = _write(tmp_path, "doc.doc", make_mhtml(html))
        doc = parse_mhtml(path)
        assert "a = b" in doc.html
        assert doc.images == []

    def test_extracts_image_parts(self, tmp_path):
        html = '<html><body><img src="hash1" alt="x"></body></html>'
        images = [("file:///C:/hash1", PNG_BYTES, "application/octet-stream")]
        path = _write(tmp_path, "doc.doc", make_mhtml(html, images))
        doc = parse_mhtml(path)
        assert len(doc.images) == 1
        part = doc.images[0]
        assert part.content_location == "file:///C:/hash1"
        assert part.data == PNG_BYTES

    def test_raises_without_html_part(self, tmp_path):
        # Craft a container whose only part is an image.
        raw = make_mhtml("<html></html>")
        # Remove the html part crudely by parsing a bad file: instead build a
        # message with no text/html by swapping the content type.
        raw = raw.replace(b"text/html", b"text/plain")
        path = _write(tmp_path, "doc.doc", raw)
        try:
            parse_mhtml(path)
        except ValueError as exc:
            assert "no text/html" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("expected ValueError")
