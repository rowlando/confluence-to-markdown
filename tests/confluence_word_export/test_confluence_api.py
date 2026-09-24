import pytest

from confluence_word_export.confluence_api import ConfluenceClient
from confluence_word_export.errors import AuthError, RootDiscoveryError
from confluence_word_export.models import Auth


class FakeResponse:
    def __init__(self, status=200, json_data=None, url="https://x.atlassian.net"):
        self.status_code = status
        self._json = json_data
        self.url = url

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


class FakeSession:
    """Serves queued responses; matches by call order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None, allow_redirects=True, **kw):
        self.calls.append((url, params))
        return self._responses.pop(0)


AUTH = Auth("a@b.com", "tok")
SITE = "https://x.atlassian.net"


class TestGetPage:
    def test_returns_page(self):
        session = FakeSession(
            [FakeResponse(json_data={"id": "100", "title": "Root", "parentId": None})]
        )
        client = ConfluenceClient(SITE, AUTH, session=session)
        page = client.get_page("100")
        assert page.id == "100"
        assert page.title == "Root"
        assert page.depth == 0

    def test_401_is_auth_error(self):
        session = FakeSession([FakeResponse(status=401)])
        client = ConfluenceClient(SITE, AUTH, session=session)
        with pytest.raises(AuthError):
            client.get_page("100")

    def test_404_is_root_discovery_error(self):
        session = FakeSession([FakeResponse(status=404)])
        client = ConfluenceClient(SITE, AUTH, session=session)
        with pytest.raises(RootDiscoveryError):
            client.get_page("100")


class TestDescendants:
    def test_follows_pagination(self):
        page1 = FakeResponse(
            json_data={
                "results": [
                    {
                        "id": "1",
                        "title": "A",
                        "type": "page",
                        "parentId": "100",
                        "depth": 1,
                    },
                    {
                        "id": "2",
                        "title": "WB",
                        "type": "whiteboard",
                        "parentId": "100",
                        "depth": 1,
                    },
                ],
                "_links": {"next": "/wiki/api/v2/pages/100/descendants?cursor=abc"},
            }
        )
        page2 = FakeResponse(
            json_data={
                "results": [
                    {
                        "id": "3",
                        "title": "B",
                        "type": "page",
                        "parentId": "1",
                        "depth": 2,
                    },
                ],
                "_links": {},
            }
        )
        session = FakeSession([page1, page2])
        client = ConfluenceClient(SITE, AUTH, session=session)
        pages = client.get_descendant_pages("100")
        # Whiteboard filtered out; both pages from both responses retained.
        assert [p.id for p in pages] == ["1", "3"]
        assert len(session.calls) == 2

    def test_ignores_non_page_types(self):
        resp = FakeResponse(
            json_data={
                "results": [
                    {
                        "id": "1",
                        "title": "folder",
                        "type": "folder",
                        "parentId": "100",
                        "depth": 1,
                    },
                    {
                        "id": "2",
                        "title": "db",
                        "type": "database",
                        "parentId": "100",
                        "depth": 1,
                    },
                ],
                "_links": {},
            }
        )
        session = FakeSession([resp])
        client = ConfluenceClient(SITE, AUTH, session=session)
        assert client.get_descendant_pages("100") == []
