"""Authentication handling.

Credentials are read only from environment variables and applied as HTTP Basic
authentication to every request. They are never logged, printed, or persisted.
"""

from __future__ import annotations

import os

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from confluence_word_export.errors import AuthError
from confluence_word_export.models import Auth

EMAIL_ENV_VAR = "CONFLUENCE_EMAIL"
TOKEN_ENV_VAR = "CONFLUENCE_API_TOKEN"

# A sensible default so credentials are never accidentally leaked via the UA.
USER_AGENT = "confluence-word-export"

# Conservative retry policy for transient failures (PRD section 21, stage 3).
_RETRY_STATUSES = (429, 500, 502, 503, 504)
_MAX_RETRIES = 3


def load_auth(env: dict[str, str] | None = None) -> Auth:
    """Load credentials from the environment.

    Raises :class:`AuthError` with a clear message if either variable is missing
    or empty. The error message never includes the token value.
    """
    source = os.environ if env is None else env

    email = (source.get(EMAIL_ENV_VAR) or "").strip()
    token = (source.get(TOKEN_ENV_VAR) or "").strip()

    missing = []
    if not email:
        missing.append(EMAIL_ENV_VAR)
    if not token:
        missing.append(TOKEN_ENV_VAR)

    if missing:
        names = " and ".join(missing)
        raise AuthError(
            f"Missing required environment variable(s): {names}. "
            f"Set {EMAIL_ENV_VAR} to your Confluence account email and "
            f"{TOKEN_ENV_VAR} to a personal API token."
        )

    return Auth(email=email, api_token=token)


def enable_system_trust_store() -> bool:
    """Make Python's TLS use the operating-system trust store, like ``curl``.

    Uses the ``truststore`` package to consult the native certificate store
    (macOS Keychain, Windows cert store, or the Linux system store), which
    includes CAs added by corporate proxies. TLS verification remains fully
    enabled. Returns ``True`` if the trust store was activated, ``False`` if
    ``truststore`` is not installed.
    """
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True


def build_session(auth: Auth, verify: bool | str | None = None) -> requests.Session:
    """Return a ``requests`` session pre-configured with Basic auth and retries.

    ``verify`` controls TLS certificate verification and is passed through to
    ``requests``:

    * ``None`` (default) uses the system trust store, honouring the standard
      ``REQUESTS_CA_BUNDLE`` / ``CURL_CA_BUNDLE`` environment variables;
    * a path string trusts an additional CA bundle (e.g. a corporate proxy CA);
    * ``False`` disables verification entirely (insecure).
    """
    session = requests.Session()
    session.auth = auth.as_basic_auth()
    session.headers.update({"User-Agent": USER_AGENT})
    if verify is not None:
        session.verify = verify

    retry = Retry(
        total=_MAX_RETRIES,
        connect=_MAX_RETRIES,
        read=_MAX_RETRIES,
        status=_MAX_RETRIES,
        backoff_factor=0.5,
        status_forcelist=_RETRY_STATUSES,
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
