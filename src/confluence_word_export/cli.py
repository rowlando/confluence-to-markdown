"""Command-line interface for the Confluence Word Export tool."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from confluence_word_export import __version__
from confluence_word_export.auth import (
    build_session,
    enable_system_trust_store,
    load_auth,
)
from confluence_word_export.confluence_api import ConfluenceClient
from confluence_word_export.downloader import Downloader
from confluence_word_export.errors import (
    EXIT_DOWNLOAD_FAILURES,
    EXIT_SUCCESS,
    ConfluenceExportError,
    UsageError,
)
from confluence_word_export.filters import build_decisions, load_ignore_terms
from confluence_word_export.hierarchy import build_hierarchy
from confluence_word_export.models import (
    STATUS_DOWNLOADED,
    STATUS_EXCLUDED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_UNSELECTED,
    DownloadResult,
    Page,
)
from confluence_word_export.urls import parse_page_url

DEFAULT_OUTPUT = "./confluence-export"
DEFAULT_IGNORE_FILE = ".confluence-word-export-ignore"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="confluence-word-export",
        description="Download a Confluence page hierarchy as Word exports.",
        epilog=(
            "Authentication is read from the CONFLUENCE_EMAIL and "
            "CONFLUENCE_API_TOKEN environment variables.\n\n"
            "Examples:\n"
            "  confluence-word-export URL --output ./exports\n"
            "  confluence-word-export URL --include security --exclude draft\n"
            "  confluence-word-export URL --list-only\n"
            "  confluence-word-export URL --include-root"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "root_page_url", metavar="ROOT_PAGE_URL", help="Confluence Cloud page URL."
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help="Output directory (default: %(default)s).",
    )
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        metavar="TEXT",
        help="Only download pages whose titles contain TEXT (repeatable).",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="TEXT",
        help="Exclude pages whose titles contain TEXT, with their subtrees "
        "(repeatable).",
    )
    parser.add_argument(
        "--ignore-file",
        default=None,
        metavar="PATH",
        help=f"Ignore file of extra exclude terms (default: ./{DEFAULT_IGNORE_FILE} if present).",
    )
    parser.add_argument(
        "--include-root",
        action="store_true",
        help="Also download the supplied root page.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Show selected pages and paths without downloading.",
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
        help="Also write a JSON Lines record of every page processed to PATH, "
        "regardless of --format (useful for scripting/auditing alongside "
        "human-readable text output).",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Replace existing Word exports."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show extra detail, including excluded and unselected pages.",
    )
    parser.add_argument(
        "--ca-bundle",
        default=None,
        metavar="PATH",
        help="Path to a CA certificate bundle to trust (e.g. a corporate proxy CA). "
        "The REQUESTS_CA_BUNDLE environment variable is also honoured.",
    )
    parser.add_argument(
        "--system-certs",
        action="store_true",
        help="Use the OS trust store (macOS Keychain, etc.) for TLS, like curl. "
        "Enabled automatically when the 'truststore' package is installed.",
    )
    parser.add_argument(
        "--no-system-certs",
        action="store_true",
        help="Do not use the OS trust store; use the bundled certifi CA list.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification (not recommended).",
    )
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
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        return _run(args)
    except ConfluenceExportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


def _resolve_ignore_path(raw: str | None) -> tuple[Path | None, bool]:
    """Return ``(path, explicit)``. Explicit means the user supplied the flag."""
    if raw is not None:
        return Path(raw), True
    default = Path(DEFAULT_IGNORE_FILE)
    return default, False


def _resolve_verify(args: argparse.Namespace) -> bool | str | None:
    """Return the TLS ``verify`` value for the session.

    ``--insecure`` wins and returns ``False``; ``--ca-bundle`` returns the
    validated path; otherwise ``None`` (default trust store + env vars).
    """
    if args.insecure:
        if args.ca_bundle:
            raise UsageError("Use either --ca-bundle or --insecure, not both.")
        return False
    if args.ca_bundle:
        path = Path(args.ca_bundle)
        if not path.is_file():
            raise UsageError(f"CA bundle not found: {path}")
        return str(path)
    return None


def _resolve_system_certs(args: argparse.Namespace) -> bool | None:
    """Return ``True``/``False`` if explicitly set, else ``None`` (auto)."""
    if args.system_certs and args.no_system_certs:
        raise UsageError("Use either --system-certs or --no-system-certs, not both.")
    if args.system_certs:
        return True
    if args.no_system_certs:
        return False
    return None


def _configure_tls(args: argparse.Namespace) -> bool | str | None:
    """Apply the TLS trust strategy and return the ``verify`` value for requests.

    Precedence: ``--insecure`` > ``--ca-bundle`` > OS trust store (default when
    available) > bundled certifi list.
    """
    verify = _resolve_verify(args)
    system_certs = _resolve_system_certs(args)

    if verify is False:  # --insecure
        if system_certs is True:
            raise UsageError("--system-certs cannot be combined with --insecure.")
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        print(
            "warning: TLS certificate verification is disabled (--insecure).",
            file=sys.stderr,
        )
        return verify

    if verify is not None:  # --ca-bundle
        if system_certs is True:
            raise UsageError("--system-certs cannot be combined with --ca-bundle.")
        return verify

    # No explicit bundle: use the OS trust store unless the user opted out.
    if system_certs is False:
        return None
    enabled = enable_system_trust_store()
    if system_certs is True and not enabled:
        raise UsageError(
            "--system-certs requires the 'truststore' package. "
            "Install it with `pip install truststore`, or use --ca-bundle."
        )
    return None


def _run(args: argparse.Namespace) -> int:
    site_url, root_page_id = parse_page_url(args.root_page_url)
    auth = load_auth()

    verify = _configure_tls(args)
    session = build_session(auth, verify=verify)

    manifest_path = Path(args.manifest) if args.manifest else None
    recorder = _Recorder(args.format, manifest_path)
    try:
        return _run_export(args, site_url, root_page_id, auth, session, recorder)
    finally:
        recorder.close()


def _run_export(args, site_url, root_page_id, auth, session, recorder) -> int:
    ignore_path, explicit = _resolve_ignore_path(args.ignore_file)
    ignore_terms = load_ignore_terms(ignore_path, explicit=explicit)
    exclude_terms = list(args.exclude) + ignore_terms

    client = ConfluenceClient(site_url, auth, session=session)
    root_page = client.get_page(root_page_id)
    descendants = client.get_descendant_pages(root_page_id)

    output_dir = Path(args.output)
    placed = build_hierarchy(root_page, descendants, output_dir)

    # Decide which pages are selected for download.
    candidates: list[Page] = list(descendants)
    if args.include_root:
        candidates = [root_page] + candidates

    decisions = build_decisions(candidates, args.include, exclude_terms)

    ignore_used = ignore_path if (ignore_terms or explicit) else None
    _print_startup_summary(
        site_url,
        root_page,
        args,
        descendants,
        decisions,
        output_dir,
        ignore_used,
        recorder,
    )

    if args.list_only:
        _print_list(
            root_page, descendants, placed, decisions, args.include_root, recorder
        )
        return EXIT_SUCCESS

    return _download_all(
        site_url,
        auth,
        session,
        root_page,
        descendants,
        placed,
        decisions,
        args,
        recorder,
    )


def _print_startup_summary(
    site_url,
    root_page,
    args,
    descendants,
    decisions,
    output_dir,
    ignore_used,
    recorder,
):
    selected = sum(1 for d in decisions.values() if d.selected)
    excluded = sum(1 for d in decisions.values() if d.excluded)
    unselected = sum(1 for d in decisions.values() if d.unselected)

    recorder.emit(
        {
            "type": "run_started",
            "site": site_url,
            "rootPageId": root_page.id,
            "rootPageTitle": root_page.title,
            "includeRoot": args.include_root,
            "descendantPages": len(descendants),
            "matchingPages": selected,
            "excludedPages": excluded,
            "unselectedPages": unselected,
            "outputDirectory": str(output_dir),
            "ignoreFile": str(ignore_used) if ignore_used is not None else None,
        }
    )
    if recorder.fmt == "json":
        return

    print("Confluence Word Export")
    print(f"  Site:              {site_url}")
    print(f"  Root page:         {root_page.title}")
    print(f"  Root page ID:      {root_page.id}")
    print(f"  Download root:     {'yes' if args.include_root else 'no'}")
    print(f"  Descendant pages:  {len(descendants)}")
    print(f"  Selected pages:    {selected}")
    print(f"  Excluded pages:    {excluded}")
    print(f"  Unselected pages:  {unselected}")
    print(f"  Output directory:  {output_dir}")
    if ignore_used is not None:
        print(f"  Ignore file:       {ignore_used}")
    print("  Note: Word exports inherit the sensitivity of their source pages.")
    print()


def _ordered_pages(root_page: Page, descendants: list[Page], placed) -> list[Page]:
    """Depth-first order for readable, hierarchical output."""
    children: dict[str | None, list[Page]] = {}
    ids = {p.id for p in descendants} | {root_page.id}
    for page in descendants:
        parent = page.parent_id if page.parent_id in ids else root_page.id
        children.setdefault(parent, []).append(page)

    for kids in children.values():
        kids.sort(
            key=lambda p: (
                p.child_position if p.child_position is not None else 1 << 30,
                placed[p.id].base_name.lower(),
            )
        )

    order: list[Page] = []

    def walk(page: Page) -> None:
        for child in children.get(page.id, []):
            order.append(child)
            walk(child)

    walk(root_page)
    return order


def _print_list(root_page, descendants, placed, decisions, include_root, recorder):
    count = 0
    if (
        include_root
        and decisions.get(root_page.id, None)
        and decisions[root_page.id].selected
    ):
        p = placed[root_page.id]
        recorder.emit(
            {
                "type": "page",
                "pageId": root_page.id,
                "title": root_page.title,
                "depth": 0,
                "path": str(p.dir_path),
            }
        )
        count += 1

    for page in _ordered_pages(root_page, descendants, placed):
        decision = decisions.get(page.id)
        if decision is None or not decision.selected:
            continue
        p = placed[page.id]
        recorder.emit(
            {
                "type": "page",
                "pageId": page.id,
                "title": page.title,
                "depth": page.depth,
                "path": str(p.dir_path),
            }
        )
        count += 1

    recorder.emit({"type": "summary", "wouldDownload": count})
    if recorder.fmt == "json":
        return

    print(f"{placed[root_page.id].base_name}/")
    if (
        include_root
        and decisions.get(root_page.id, None)
        and decisions[root_page.id].selected
    ):
        p = placed[root_page.id]
        print(f"{p.base_name} [pageId: {root_page.id}]")

    for page in _ordered_pages(root_page, descendants, placed):
        decision = decisions.get(page.id)
        if decision is None or not decision.selected:
            continue
        p = placed[page.id]
        indent = "  " * page.depth
        print(f"{indent}{p.base_name}  [pageId: {page.id}] -> {p.dir_path}")
    print()


def _download_all(
    site_url,
    auth,
    session,
    root_page,
    descendants,
    placed,
    decisions,
    args,
    recorder,
) -> int:
    downloader = Downloader(site_url, auth, session=session)

    # Ensure the root directory always exists (PRD 12.1).
    placed[root_page.id].dir_path.mkdir(parents=True, exist_ok=True)

    pages = _ordered_pages(root_page, descendants, placed)
    if args.include_root:
        pages = [root_page] + pages

    results: list[DownloadResult] = []
    for page in pages:
        decision = decisions.get(page.id)
        if decision is None or not decision.selected:
            reason = decision.reason if decision else "n/a"
            status = (
                STATUS_EXCLUDED if decision and decision.excluded else STATUS_UNSELECTED
            )
            not_selected = DownloadResult(page, status, None, None)
            recorder.emit(_result_json(not_selected, reason=reason))
            if recorder.fmt != "json" and args.verbose:
                print(f"{status:<10}  {page.title}  ({reason})")
            results.append(not_selected)
            continue

        result = downloader.download(placed[page.id], overwrite=args.overwrite)
        _print_result(result, args.verbose, recorder)
        results.append(result)

    return _print_final_summary(descendants, decisions, results, recorder)


def _result_json(result: DownloadResult, reason: str | None = None) -> dict:
    return {
        "type": "result",
        "pageId": result.page.id,
        "title": result.page.title,
        "status": result.status,
        "path": str(result.path) if result.path else None,
        "error": result.error,
        "reason": reason,
    }


def _print_result(result: DownloadResult, verbose: bool, recorder) -> None:
    recorder.emit(_result_json(result))
    if recorder.fmt == "json":
        return
    status = result.status
    title = result.page.title
    if status == STATUS_DOWNLOADED:
        print(f"DOWNLOADED  {title} -> {result.path}")
    elif status == STATUS_SKIPPED:
        print(f"SKIPPED     {title} (exists: {result.path})")
    elif status == STATUS_FAILED:
        print(f"FAILED      {title}: {result.error}", file=sys.stderr)


def _print_final_summary(descendants, decisions, results, recorder) -> int:
    selected = sum(1 for d in decisions.values() if d.selected)
    downloaded = sum(1 for r in results if r.status == STATUS_DOWNLOADED)
    skipped = sum(1 for r in results if r.status == STATUS_SKIPPED)
    excluded = sum(1 for r in results if r.status == STATUS_EXCLUDED)
    unselected = sum(1 for r in results if r.status == STATUS_UNSELECTED)
    failed = sum(1 for r in results if r.status == STATUS_FAILED)

    recorder.emit(
        {
            "type": "summary",
            "discovered": len(descendants),
            "matched": selected,
            "downloaded": downloaded,
            "skipped": skipped,
            "excluded": excluded,
            "unselected": unselected,
            "failed": failed,
        }
    )
    if recorder.fmt == "json":
        return EXIT_DOWNLOAD_FAILURES if failed else EXIT_SUCCESS

    print()
    print("Run complete" if failed == 0 else "Run finished with failures")
    print()
    print(f"Pages discovered:  {len(descendants)}")
    print(f"Pages selected:    {selected}")
    print(f"Downloaded:        {downloaded}")
    print(f"Skipped existing:  {skipped}")
    print(f"Excluded:          {excluded}")
    print(f"Unselected:        {unselected}")
    print(f"Failed:            {failed}")

    return EXIT_DOWNLOAD_FAILURES if failed else EXIT_SUCCESS
