"""Exit codes and exception types for the CLI.

Exit codes follow PRD section 15.5:

* 0  Operation completed without download failures
* 1  One or more pages failed to download
* 2  Invalid arguments or configuration
* 3  Authentication or authorisation failure
* 4  Root page discovery failure
"""

from __future__ import annotations

EXIT_SUCCESS = 0
EXIT_DOWNLOAD_FAILURES = 1
EXIT_INVALID_USAGE = 2
EXIT_AUTH_FAILURE = 3
EXIT_ROOT_DISCOVERY_FAILURE = 4


class ConfluenceExportError(Exception):
    """Base class for errors that should map to a specific CLI exit code."""

    exit_code = EXIT_INVALID_USAGE


class UsageError(ConfluenceExportError):
    """Invalid arguments or configuration (exit code 2)."""

    exit_code = EXIT_INVALID_USAGE


class AuthError(ConfluenceExportError):
    """Authentication or authorisation failure (exit code 3)."""

    exit_code = EXIT_AUTH_FAILURE


class RootDiscoveryError(ConfluenceExportError):
    """The root page could not be retrieved (exit code 4)."""

    exit_code = EXIT_ROOT_DISCOVERY_FAILURE


TLS_HINT = (
    "TLS certificate verification failed. This usually means a proxy or "
    "corporate network is intercepting HTTPS with its own certificate "
    "authority. Options:\n"
    "  * point the tool at your organisation's CA bundle:\n"
    "      --ca-bundle /path/to/corporate-ca.pem\n"
    "      (or export REQUESTS_CA_BUNDLE=/path/to/corporate-ca.pem)\n"
    "  * as a last resort, skip verification with --insecure (not recommended)."
)
