"""Command-line interface for the Word-to-Markdown converter."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from word_to_markdown import __version__
from word_to_markdown.backends import BACKEND_NAMES, get_backend
from word_to_markdown.convert import (
    STATUS_CONVERTED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    convert_file,
)
from word_to_markdown.errors import (
    EXIT_CONVERSION_FAILURES,
    EXIT_SUCCESS,
    UsageError,
    WordToMarkdownError,
)
from word_to_markdown.walk import find_inputs, output_path_for

DEFAULT_OUTPUT = "./markdown-export"
DEFAULT_BACKEND = "markitdown"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="word-to-markdown",
        description=(
            "Convert a directory of Word documents (including Confluence "
            "'Export to Word' MHTML .doc files) into a mirrored tree of "
            "Markdown, which is friendlier for agentic tools."
        ),
        epilog=(
            "Examples:\n"
            "  word-to-markdown ./confluence-export --output ./markdown\n"
            "  word-to-markdown ./docs --backend pandoc --clean-names\n"
            "  word-to-markdown ./docs --list-only"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "input_dir", metavar="INPUT_DIR", help="Directory of documents to convert."
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output directory (default: %(default)s).",
    )
    parser.add_argument(
        "--backend",
        choices=BACKEND_NAMES,
        default=DEFAULT_BACKEND,
        help="HTML->Markdown backend (default: %(default)s).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing Markdown/assets (default: skip existing).",
    )
    parser.add_argument(
        "--clean-names",
        action="store_true",
        help="Turn Confluence '+'-encoded names into spaced names.",
    )
    parser.add_argument(
        "--flatten",
        action="store_true",
        help="Do not mirror subdirectories; write every .md in the output root.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Show what would be converted without writing anything.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format for progress/results (default: %(default)s). "
        "'json' writes one JSON object per line (JSON Lines) to stdout for "
        "piping into jq/xargs/etc.; human-readable notices move to stderr.",
    )
    parser.add_argument(
        "--manifest",
        default=None,
        metavar="PATH",
        help="Also write a JSON Lines record of every file processed to PATH, "
        "regardless of --format (useful for scripting/auditing alongside "
        "human-readable text output).",
    )
    parser.add_argument("--verbose", action="store_true", help="Show extra detail.")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


class _Recorder:
    """Emits JSON Lines events to stdout (``--format json``) and/or a manifest
    file (``--manifest PATH``), independent of each other.

    A manifest is written whenever ``--manifest`` is given, even in the
    default ``text`` format, so a human can watch progress in the terminal
    while still getting a durable, parseable record of the run.
    """

    def __init__(self, fmt: str, manifest_path: Path | None) -> None:
        self.fmt = fmt
        self._handle = None
        if manifest_path is not None:
            try:
                self._handle = manifest_path.open("w", encoding="utf-8")
            except OSError as exc:
                raise UsageError(
                    f"cannot write manifest {manifest_path}: {exc}"
                ) from exc

    def emit(self, obj: dict) -> None:
        if self.fmt != "json" and self._handle is None:
            return
        line = json.dumps(obj, default=str)
        if self.fmt == "json":
            print(line)
        if self._handle is not None:
            self._handle.write(line + "\n")

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _run(args)
    except WordToMarkdownError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


def _run(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        raise UsageError(f"input directory not found: {input_dir}")

    manifest_path = Path(args.manifest) if args.manifest else None
    recorder = _Recorder(args.format, manifest_path)
    try:
        return _run_convert(args, input_dir, recorder)
    finally:
        recorder.close()


def _run_convert(args, input_dir, recorder) -> int:
    output_dir = Path(args.output)
    sources = find_inputs(input_dir)

    _print_startup_summary(input_dir, output_dir, args, len(sources), recorder)

    if not sources:
        recorder.emit({"type": "summary", "converted": 0, "reason": "no_inputs"})
        if recorder.fmt != "json":
            print("No convertible documents found.")
        return EXIT_SUCCESS

    plan = _plan_outputs(sources, input_dir, output_dir, args)

    if args.list_only:
        for source, output in plan:
            recorder.emit(
                {"type": "file", "source": str(source), "output": str(output)}
            )
        recorder.emit({"type": "summary", "wouldConvert": len(plan)})
        if recorder.fmt != "json":
            for source, output in plan:
                print(f"{source}  ->  {output}")
            print(f"\n{len(plan)} file(s) would be converted.")
        return EXIT_SUCCESS

    backend = get_backend(args.backend)
    return _convert_all(plan, backend, args, recorder)


def _plan_outputs(sources, input_dir, output_dir, args) -> list[tuple[Path, Path]]:
    """Compute (source, output) pairs, disambiguating flatten collisions."""
    plan: list[tuple[Path, Path]] = []
    claimed: dict[Path, int] = {}
    for source in sources:
        output = output_path_for(
            source,
            input_dir,
            output_dir,
            flatten=args.flatten,
            clean_names=args.clean_names,
        )
        output = _disambiguate(output, claimed)
        plan.append((source, output))
    return plan


def _disambiguate(output: Path, claimed: dict[Path, int]) -> Path:
    """Ensure two inputs never map to the same output path in one run."""
    if output not in claimed:
        claimed[output] = 1
        return output
    stem, suffix = output.stem, output.suffix
    while True:
        claimed[output] = claimed.get(output, 1) + 1
        candidate = output.with_name(f"{stem}-{claimed[output]}{suffix}")
        if candidate not in claimed:
            claimed[candidate] = 1
            return candidate


def _convert_all(plan, backend, args, recorder) -> int:
    converted = skipped = failed = 0
    total_images = 0

    for source, output in plan:
        result = convert_file(source, output, backend, overwrite=args.overwrite)
        recorder.emit(
            {
                "type": "result",
                "source": str(source),
                "output": str(output),
                "status": result.status,
                "images": result.images,
                "error": result.error,
            }
        )
        if result.status == STATUS_CONVERTED:
            converted += 1
            total_images += result.images
            if recorder.fmt != "json":
                extra = f" (+{result.images} image(s))" if result.images else ""
                print(f"CONVERTED  {source.name} -> {output}{extra}")
        elif result.status == STATUS_SKIPPED:
            skipped += 1
            if recorder.fmt != "json" and args.verbose:
                print(f"SKIPPED    {source.name} (exists: {output})")
        elif result.status == STATUS_FAILED:
            failed += 1
            if recorder.fmt != "json":
                print(f"FAILED     {source.name}: {result.error}", file=sys.stderr)

    _print_final_summary(converted, skipped, failed, total_images, recorder)
    return EXIT_CONVERSION_FAILURES if failed else EXIT_SUCCESS


def _print_startup_summary(input_dir, output_dir, args, count, recorder) -> None:
    recorder.emit(
        {
            "type": "run_started",
            "inputDirectory": str(input_dir),
            "outputDirectory": str(output_dir),
            "backend": args.backend,
            "documentsFound": count,
        }
    )
    if recorder.fmt == "json":
        return

    print("Word to Markdown")
    print(f"  Input directory:   {input_dir}")
    print(f"  Output directory:  {output_dir}")
    print(f"  Backend:           {args.backend}")
    print(f"  Documents found:   {count}")
    print()


def _print_final_summary(converted, skipped, failed, images, recorder) -> None:
    recorder.emit(
        {
            "type": "summary",
            "converted": converted,
            "skipped": skipped,
            "failed": failed,
            "images": images,
        }
    )
    if recorder.fmt == "json":
        return

    print()
    print("Conversion complete" if failed == 0 else "Conversion finished with failures")
    print()
    print(f"Converted:         {converted}")
    print(f"Skipped existing:  {skipped}")
    print(f"Failed:            {failed}")
    print(f"Images extracted:  {images}")
