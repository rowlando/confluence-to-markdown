"""HTML/Word -> Markdown conversion backends.

Two interchangeable backends are provided:

* :class:`MarkitdownBackend` (default) — uses the ``markitdown`` library, which
  produces LLM-friendly Markdown.
* :class:`PandocBackend` (``--backend pandoc``) — shells out to ``pandoc`` for
  higher-fidelity tables, at the cost of an external binary.

Both expose the same small interface: turn an HTML string (already cleaned and
with rewritten asset links) or a real Word file into Markdown text.
"""

from __future__ import annotations

import io
import shutil
import subprocess
from pathlib import Path

from word_to_markdown.errors import BackendError


class Backend:
    """Common interface for conversion backends."""

    name = "backend"

    def check_available(self) -> None:
        """Raise :class:`BackendError` if the backend cannot run."""

    def convert_html(self, html: str, source_name: str) -> str:
        raise NotImplementedError

    def convert_file(self, path: Path) -> str:
        raise NotImplementedError


class MarkitdownBackend(Backend):
    """Convert using the ``markitdown`` library (default)."""

    name = "markitdown"

    def __init__(self) -> None:
        self._md = None

    def check_available(self) -> None:
        try:
            from markitdown import MarkItDown  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised via message
            raise BackendError(
                "The 'markitdown' package is required for the default backend. "
                "Install it with `pip install markitdown`, or use "
                "`--backend pandoc`."
            ) from exc

    def _engine(self):
        if self._md is None:
            from markitdown import MarkItDown

            self._md = MarkItDown()
        return self._md

    def convert_html(self, html: str, source_name: str) -> str:
        stream = io.BytesIO(html.encode("utf-8"))
        result = self._engine().convert_stream(stream, file_extension=".html")
        return result.text_content

    def convert_file(self, path: Path) -> str:
        result = self._engine().convert(str(path))
        return result.text_content


class PandocBackend(Backend):
    """Convert by shelling out to ``pandoc``."""

    name = "pandoc"

    # GitHub-Flavored Markdown with unwrapped lines keeps tables intact and
    # avoids spurious hard line breaks in prose.
    _TO = "gfm"
    _COMMON = ("--wrap=none",)

    def check_available(self) -> None:
        if shutil.which("pandoc") is None:
            raise BackendError(
                "The 'pandoc' binary was not found on PATH. Install pandoc "
                "(https://pandoc.org/installing.html), or use the default "
                "markitdown backend."
            )

    def convert_html(self, html: str, source_name: str) -> str:
        return self._run(("--from=html", f"--to={self._TO}", *self._COMMON), html)

    def convert_file(self, path: Path) -> str:
        fmt = "docx" if path.suffix.lower() == ".docx" else None
        args = [f"--to={self._TO}", *self._COMMON, str(path)]
        if fmt:
            args.insert(0, f"--from={fmt}")
        return self._run(tuple(args), None)

    def _run(self, args: tuple[str, ...], stdin: str | None) -> str:
        try:
            proc = subprocess.run(
                ("pandoc", *args),
                input=stdin.encode("utf-8") if stdin is not None else None,
                capture_output=True,
                check=True,
            )
        except FileNotFoundError as exc:  # pragma: no cover
            raise BackendError("pandoc binary not found on PATH.") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.decode("utf-8", errors="replace").strip()
            raise BackendError(f"pandoc failed: {detail}") from exc
        return proc.stdout.decode("utf-8", errors="replace")


_BACKENDS = {
    MarkitdownBackend.name: MarkitdownBackend,
    PandocBackend.name: PandocBackend,
}

BACKEND_NAMES = tuple(_BACKENDS)


def get_backend(name: str) -> Backend:
    """Return a ready, availability-checked backend by name."""
    try:
        factory = _BACKENDS[name]
    except KeyError:
        raise BackendError(
            f"Unknown backend {name!r}. Choose from: {', '.join(BACKEND_NAMES)}."
        ) from None
    backend = factory()
    backend.check_available()
    return backend
