import pytest

from confluence_word_export.auth import load_auth
from confluence_word_export.errors import AuthError, UsageError
from confluence_word_export.urls import parse_page_url


class TestParsePageUrl:
    def test_spaces_pages_url(self):
        site, page_id = parse_page_url(
            "https://example.atlassian.net/wiki/spaces/TEAM/pages/4547346548/Acme+Docs"
        )
        assert site == "https://example.atlassian.net"
        assert page_id == "4547346548"

    def test_short_pages_url(self):
        site, page_id = parse_page_url("https://example.atlassian.net/wiki/pages/999")
        assert site == "https://example.atlassian.net"
        assert page_id == "999"

    def test_legacy_viewpage_url(self):
        site, page_id = parse_page_url(
            "https://example.atlassian.net/wiki/pages/viewpage.action?pageId=42"
        )
        assert page_id == "42"

    def test_rejects_http(self):
        with pytest.raises(UsageError):
            parse_page_url("http://example.atlassian.net/wiki/spaces/X/pages/1/T")

    def test_rejects_space_home(self):
        with pytest.raises(UsageError):
            parse_page_url("https://example.atlassian.net/wiki/spaces/LTA/overview")

    def test_rejects_unsupported_host(self):
        with pytest.raises(UsageError):
            parse_page_url("https://evil.example.com/wiki/spaces/X/pages/1/T")

    def test_rejects_malformed(self):
        with pytest.raises(UsageError):
            parse_page_url("not a url")

    def test_rejects_empty(self):
        with pytest.raises(UsageError):
            parse_page_url("")


class TestLoadAuth:
    def test_loads_from_env(self):
        auth = load_auth(
            {"CONFLUENCE_EMAIL": "a@b.com", "CONFLUENCE_API_TOKEN": "secret"}
        )
        assert auth.email == "a@b.com"
        assert auth.api_token == "secret"
        assert auth.as_basic_auth() == ("a@b.com", "secret")

    def test_missing_both(self):
        with pytest.raises(AuthError) as exc:
            load_auth({})
        assert "CONFLUENCE_EMAIL" in str(exc.value)
        assert "CONFLUENCE_API_TOKEN" in str(exc.value)

    def test_missing_token(self):
        with pytest.raises(AuthError):
            load_auth({"CONFLUENCE_EMAIL": "a@b.com"})

    def test_token_not_in_repr(self):
        auth = load_auth(
            {"CONFLUENCE_EMAIL": "a@b.com", "CONFLUENCE_API_TOKEN": "supersecret"}
        )
        assert "supersecret" not in repr(auth)
