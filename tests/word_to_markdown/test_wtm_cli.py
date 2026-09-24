import json

import pytest

from tests.word_to_markdown.wtm_fixtures import make_mhtml
from word_to_markdown.cli import main


def _make_tree(tmp_path):
    src_dir = tmp_path / "in"
    (src_dir / "sub").mkdir(parents=True)
    (src_dir / "One.doc").write_bytes(make_mhtml("<h1>One</h1>"))
    (src_dir / "sub" / "Two.doc").write_bytes(make_mhtml("<h1>Two</h1>"))
    return src_dir


class TestCli:
    def test_converts_tree_and_mirrors_structure(self, tmp_path, capsys):
        src_dir = _make_tree(tmp_path)
        out_dir = tmp_path / "out"

        code = main([str(src_dir), "--output", str(out_dir)])

        assert code == 0
        assert (out_dir / "One.md").is_file()
        assert (out_dir / "sub" / "Two.md").is_file()

    def test_skips_on_second_run(self, tmp_path, capsys):
        src_dir = _make_tree(tmp_path)
        out_dir = tmp_path / "out"

        assert main([str(src_dir), "--output", str(out_dir)]) == 0
        capsys.readouterr()
        assert main([str(src_dir), "--output", str(out_dir)]) == 0
        out = capsys.readouterr().out
        assert "Skipped existing:  2" in out

    def test_list_only_writes_nothing(self, tmp_path, capsys):
        src_dir = _make_tree(tmp_path)
        out_dir = tmp_path / "out"

        code = main([str(src_dir), "--output", str(out_dir), "--list-only"])

        assert code == 0
        assert not out_dir.exists()
        assert "would be converted" in capsys.readouterr().out

    def test_missing_input_dir_is_usage_error(self, tmp_path, capsys):
        code = main([str(tmp_path / "nope"), "--output", str(tmp_path / "o")])
        assert code == 2
        assert "input directory not found" in capsys.readouterr().err

    def test_empty_dir_succeeds(self, tmp_path, capsys):
        src_dir = tmp_path / "empty"
        src_dir.mkdir()
        code = main([str(src_dir), "--output", str(tmp_path / "o")])
        assert code == 0
        assert "No convertible documents found." in capsys.readouterr().out

    def test_invalid_backend_rejected_by_argparse(self, tmp_path):
        src_dir = _make_tree(tmp_path)
        with pytest.raises(SystemExit) as exc:
            main([str(src_dir), "--backend", "nope"])
        assert exc.value.code == 2

    def test_clean_names_applied(self, tmp_path):
        src_dir = tmp_path / "in"
        src_dir.mkdir()
        (src_dir / "Guardrail+1.doc").write_bytes(make_mhtml("<h1>G1</h1>"))
        out_dir = tmp_path / "out"

        assert main([str(src_dir), "--output", str(out_dir), "--clean-names"]) == 0
        assert (out_dir / "Guardrail 1.md").is_file()

    def test_format_json_emits_json_lines_and_nothing_else(self, tmp_path, capsys):
        src_dir = _make_tree(tmp_path)
        out_dir = tmp_path / "out"

        code = main([str(src_dir), "--output", str(out_dir), "--format", "json"])
        out = capsys.readouterr().out

        assert code == 0
        lines = [json.loads(line) for line in out.splitlines() if line]
        types = [line["type"] for line in lines]
        assert types == ["run_started", "result", "result", "summary"]
        assert lines[-1]["converted"] == 2
        result_lines = [line for line in lines if line["type"] == "result"]
        assert {line["status"] for line in result_lines} == {"converted"}

    def test_list_only_format_json(self, tmp_path, capsys):
        src_dir = _make_tree(tmp_path)
        out_dir = tmp_path / "out"

        code = main(
            [str(src_dir), "--output", str(out_dir), "--list-only", "--format", "json"]
        )
        out = capsys.readouterr().out

        assert code == 0
        lines = [json.loads(line) for line in out.splitlines() if line]
        assert [line["type"] for line in lines] == [
            "run_started",
            "file",
            "file",
            "summary",
        ]
        assert lines[-1]["wouldConvert"] == 2

    def test_manifest_written_alongside_text_output(self, tmp_path, capsys):
        src_dir = _make_tree(tmp_path)
        out_dir = tmp_path / "out"
        manifest = tmp_path / "manifest.jsonl"

        code = main(
            [str(src_dir), "--output", str(out_dir), "--manifest", str(manifest)]
        )
        out = capsys.readouterr().out

        assert code == 0
        # Human-readable text output is unaffected by --manifest.
        assert "CONVERTED" in out
        lines = [json.loads(line) for line in manifest.read_text().splitlines()]
        assert [line["type"] for line in lines] == [
            "run_started",
            "result",
            "result",
            "summary",
        ]
