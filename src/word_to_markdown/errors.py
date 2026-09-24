"""Exit codes and exception types for the word-to-markdown CLI.

Exit codes:

* 0  Completed with no conversion failures (skips still count as success)
* 1  One or more files failed to convert
* 2  Invalid arguments or configuration
"""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_CONVERSION_FAILURES = 1
EXIT_INVALID_USAGE = 2


class WordToMarkdownError(Exception):
    """Base class for errors that map to a specific CLI exit code."""

    exit_code = EXIT_INVALID_USAGE


class UsageError(WordToMarkdownError):
    """Invalid arguments or configuration (exit code 2)."""

    exit_code = EXIT_INVALID_USAGE


class BackendError(WordToMarkdownError):
    """A conversion backend is unavailable or misconfigured (exit code 2)."""

    exit_code = EXIT_INVALID_USAGE
