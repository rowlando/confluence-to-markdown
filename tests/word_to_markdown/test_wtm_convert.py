from tests.word_to_markdown.wtm_fixtures import PNG_BYTES, FakeBackend, make_mhtml
from word_to_markdown.convert import (
    STATUS_CONVERTED,
    STATUS_SKIPPED,
    convert_file,
)


def _write_doc(tmp_path, name, html, images=None):
    path = tmp_path / name
    path.write_bytes(make_mhtml(html, images))
    return path


class TestConvertFile:
    def test_converts_mhtml_via_html_backend(self, tmp_path):
        src = _write_doc(tmp_path, "doc.doc", "<h1>Title</h1>")
        out = tmp_path / "out.md"
        backend = FakeBackend()

        result = convert_file(src, out, backend, overwrite=False)

        assert result.status == STATUS_CONVERTED
        assert out.read_text().startswith("# from-html")
        assert backend.html_calls  # went through the HTML path
        assert not backend.file_calls

    def test_extracts_assets_for_mhtml_images(self, tmp_path):
        html = '<img src="hash1" alt="x">'
        images = [("file:///C:/hash1", PNG_BYTES, "application/octet-stream")]
        src = _write_doc(tmp_path, "doc.doc", html, images)
        out = tmp_path / "out.md"

        result = convert_file(src, out, FakeBackend(), overwrite=False)

        assert result.status == STATUS_CONVERTED
        assert result.images == 1
        assets = tmp_path / "out.assets"
        assert assets.is_dir()
        assert len(list(assets.iterdir())) == 1

    def test_skips_existing_without_overwrite(self, tmp_path):
        src = _write_doc(tmp_path, "doc.doc", "<h1>Title</h1>")
        out = tmp_path / "out.md"
        out.write_text("existing")

        result = convert_file(src, out, FakeBackend(), overwrite=False)

        assert result.status == STATUS_SKIPPED
        assert out.read_text() == "existing"

    def test_overwrites_when_requested(self, tmp_path):
        src = _write_doc(tmp_path, "doc.doc", "<h1>Title</h1>")
        out = tmp_path / "out.md"
        out.write_text("existing")

        result = convert_file(src, out, FakeBackend(), overwrite=True)

        assert result.status == STATUS_CONVERTED
        assert "from-html" in out.read_text()

    def test_plain_html_uses_html_backend(self, tmp_path):
        src = tmp_path / "page.html"
        src.write_text("<h1>Hi</h1>")
        out = tmp_path / "out.md"
        backend = FakeBackend()

        result = convert_file(src, out, backend, overwrite=False)

        assert result.status == STATUS_CONVERTED
        assert backend.html_calls
        assert not backend.file_calls

    def test_docx_uses_file_backend(self, tmp_path):
        # A .docx is handed straight to the backend (no MHTML parsing).
        src = tmp_path / "real.docx"
        src.write_bytes(b"PK\x03\x04 not really a docx")
        out = tmp_path / "out.md"
        backend = FakeBackend()

        result = convert_file(src, out, backend, overwrite=False)

        assert result.status == STATUS_CONVERTED
        assert backend.file_calls
        assert not backend.html_calls


class TestMarkitdownBackendSmoke:
    def test_real_markitdown_conversion(self, tmp_path):
        from word_to_markdown.backends import get_backend

        src = _write_doc(tmp_path, "doc.doc", "<h1>Hello World</h1><p>Body.</p>")
        out = tmp_path / "out.md"

        result = convert_file(src, out, get_backend("markitdown"), overwrite=False)

        assert result.status == STATUS_CONVERTED
        text = out.read_text()
        assert "Hello World" in text
        assert "Body." in text
