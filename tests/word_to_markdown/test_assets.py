from tests.word_to_markdown.wtm_fixtures import PNG_BYTES
from word_to_markdown.assets import extract_assets
from word_to_markdown.mhtml import ImagePart, MhtmlDocument


def _doc(html: str, images):
    return MhtmlDocument(html=html, images=images)


class TestExtractAssets:
    def test_no_images_returns_html_unchanged(self, tmp_path):
        doc = _doc("<p>hi</p>", [])
        html, count = extract_assets(doc, tmp_path / "a.assets", "a.assets")
        assert count == 0
        assert html == "<p>hi</p>"

    def test_writes_and_rewrites_by_content_location_basename(self, tmp_path):
        part = ImagePart(
            content_type="application/octet-stream",
            data=PNG_BYTES,
            content_location="file:///C:/deadbeef",
        )
        doc = _doc('<img src="deadbeef" alt="x">', [part])
        assets_dir = tmp_path / "a.assets"
        html, count = extract_assets(doc, assets_dir, "a.assets")

        assert count == 1
        written = list(assets_dir.iterdir())
        assert len(written) == 1
        # Magic bytes -> .png even though content-type was octet-stream.
        assert written[0].suffix == ".png"
        assert f"a.assets/{written[0].name}" in html

    def test_deduplicates_repeated_reference(self, tmp_path):
        part = ImagePart(
            content_type="image/png",
            data=PNG_BYTES,
            content_location="file:///C:/x",
        )
        doc = _doc('<img src="x"><img src="x">', [part])
        assets_dir = tmp_path / "a.assets"
        html, count = extract_assets(doc, assets_dir, "a.assets")
        assert count == 1
        assert len(list(assets_dir.iterdir())) == 1
        assert html.count("a.assets/") == 2

    def test_resolves_cid_reference(self, tmp_path):
        part = ImagePart(
            content_type="image/png",
            data=PNG_BYTES,
            content_id="img-1",
        )
        doc = _doc('<img src="cid:img-1">', [part])
        assets_dir = tmp_path / "a.assets"
        html, count = extract_assets(doc, assets_dir, "a.assets")
        assert count == 1
        assert "a.assets/" in html

    def test_unresolved_reference_is_left_alone(self, tmp_path):
        doc = _doc('<img src="http://example.com/x.png">', [])
        html, count = extract_assets(doc, tmp_path / "a.assets", "a.assets")
        assert count == 0
        assert "http://example.com/x.png" in html
