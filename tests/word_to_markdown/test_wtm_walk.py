from pathlib import Path

from word_to_markdown.walk import find_inputs, output_path_for


class TestFindInputs:
    def test_finds_supported_extensions_recursively(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.doc").write_bytes(b"x")
        (tmp_path / "sub" / "b.docx").write_bytes(b"x")
        (tmp_path / "sub" / "c.html").write_bytes(b"x")
        (tmp_path / "ignore.txt").write_bytes(b"x")

        found = find_inputs(tmp_path)
        names = sorted(p.name for p in found)
        assert names == ["a.doc", "b.docx", "c.html"]


class TestOutputPathFor:
    def test_mirrors_structure_and_swaps_extension(self, tmp_path):
        src = tmp_path / "dir" / "Guardrail+1.doc"
        out = output_path_for(src, tmp_path, Path("/out"))
        assert out == Path("/out/dir/Guardrail+1.md")

    def test_flatten_drops_subdirectories(self, tmp_path):
        src = tmp_path / "dir" / "deep" / "File.doc"
        out = output_path_for(src, tmp_path, Path("/out"), flatten=True)
        assert out == Path("/out/File.md")

    def test_clean_names_replaces_plus(self, tmp_path):
        src = tmp_path / "Guardrail+1+-+Secure.doc"
        out = output_path_for(src, tmp_path, Path("/out"), clean_names=True)
        assert out == Path("/out/Guardrail 1 - Secure.md")

    def test_clean_names_applies_to_directories(self, tmp_path):
        src = tmp_path / "My+Dir" / "My+File.doc"
        out = output_path_for(src, tmp_path, Path("/out"), clean_names=True)
        assert out == Path("/out/My Dir/My File.md")
