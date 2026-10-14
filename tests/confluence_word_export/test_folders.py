import json
from pathlib import Path

import confluence_word_export.cli as cli_mod
from confluence_word_export.cli import main
from confluence_word_export.confluence_api import ConfluenceClient
from confluence_word_export.filters import build_decisions
from confluence_word_export.hierarchy import build_hierarchy
from confluence_word_export.models import OUTCOME_EXCLUDED, Auth, Page

from .test_cli import WORD_BODY, FakeResp
from .test_confluence_api import AUTH, SITE, FakeResponse, FakeSession

URL = "https://x.atlassian.net/wiki/spaces/TEAM/pages/100/Acme+Docs"


def item(iid, parent, depth, typ="page", title=None):
    return {
        "id": iid,
        "title": title or iid,
        "type": typ,
        "parentId": parent,
        "depth": depth,
    }


def node(pid, title, parent, depth=1, typ="page", pos=None):
    return Page(pid, title, parent, depth, pos, content_type=typ)


class TestApi:
    def test_keeps_folders(self):
        resp = FakeResponse(
            json_data={"results": [item("f1", "100", 1, "folder"), item("p1", "f1", 2)]}
        )
        client = ConfluenceClient(SITE, AUTH, session=FakeSession([resp]))
        pages = client.get_descendant_pages("100")
        assert [(p.id, p.content_type) for p in pages] == [
            ("f1", "folder"),
            ("p1", "page"),
        ]
        assert pages[0].is_folder and not pages[1].is_folder

    def test_folder_at_depth_cap_uses_folders_endpoint(self):
        first = FakeResponse(
            json_data={
                "results": [
                    item("d1", "100", 1),
                    item("d2", "d1", 2),
                    item("d3", "d2", 3),
                    item("d4", "d3", 4),
                    item("f5", "d4", 5, "folder"),
                ]
            }
        )
        second = FakeResponse(json_data={"results": [item("d6", "f5", 1)]})
        session = FakeSession([first, second])
        client = ConfluenceClient(SITE, AUTH, session=session)
        pages = client.get_descendant_pages("100")
        assert pages[-1].id == "d6" and pages[-1].depth == 6
        assert session.calls[1][0].endswith("/wiki/api/v2/folders/f5/descendants")

    def test_ignores_other_types(self):
        resp = FakeResponse(json_data={"results": [item("w", "100", 1, "whiteboard")]})
        client = ConfluenceClient(SITE, AUTH, session=FakeSession([resp]))
        assert client.get_descendant_pages("100") == []


class TestHierarchyAndFilters:
    root = node("100", "Acme Docs", None, 0)

    def test_children_nest_under_folder(self):
        folder = node("f", "Archive", "100", typ="folder")
        child = node("p", "Old page", "f", 2)
        placed = build_hierarchy(self.root, [folder, child], Path("out"))
        assert placed["p"].parent_dir == Path("out/Acme Docs/Archive")

    def test_page_and_folder_name_collision(self):
        page = node("1", "Dup", "100", pos=0)
        folder = node("2", "Dup", "100", typ="folder", pos=1)
        placed = build_hierarchy(self.root, [page, folder], Path("out"))
        assert placed["1"].base_name != placed["2"].base_name

    def test_exclude_folder_prunes_subtree(self):
        folder = node("f", "Archive", "100", typ="folder")
        child = node("p", "Old page", "f", 2)
        other = node("o", "Keep", "100")
        decisions = build_decisions([folder, child, other], [], ["archive"])
        assert decisions["f"].outcome == OUTCOME_EXCLUDED
        assert decisions["p"].outcome == OUTCOME_EXCLUDED
        assert decisions["o"].selected


class FolderSession:
    def __init__(self):
        self.auth = None
        self.headers = {}
        self.urls = []

    def get(self, url, params=None, **kw):
        self.urls.append(url)
        if url.endswith("/descendants"):
            return FakeResp(
                json_data={
                    "results": [
                        item("f", "100", 1, "folder", "Archive"),
                        item("p", "f", 2, title="Old page"),
                        item("q", "100", 1, title="Live"),
                    ]
                }
            )
        if "/api/v2/folders/" in url:
            return FakeResp(json_data={"id": "900", "title": "Infra", "type": "folder"})
        if "/api/v2/pages/" in url:
            return FakeResp(json_data={"id": "100", "title": "Acme Docs"})
        if "/wiki/exportword" in url:
            pid = params["pageId"]
            return FakeResp(
                headers={
                    "Content-Type": "application/msword",
                    "Content-Disposition": f'attachment; filename="page-{pid}.doc"',
                },
                body=WORD_BODY,
                url=url,
            )
        raise AssertionError(url)


def _patch(monkeypatch):
    session = FolderSession()
    monkeypatch.setattr(cli_mod, "load_auth", lambda: Auth("a@b.com", "tok"))
    monkeypatch.setattr(cli_mod, "enable_system_trust_store", lambda: True)
    monkeypatch.setattr(cli_mod, "build_session", lambda auth, verify=None: session)
    monkeypatch.setattr(cli_mod, "DEFAULT_IGNORE_FILE", "__none__")
    return session


class TestCli:
    def test_list_only_shows_folders(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        assert main([URL, "--list-only", "--output", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "Archive/  [folderId: f]" in out
        assert "Old page" in out

    def test_list_only_json(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        args = [URL, "--list-only", "--output", str(tmp_path), "--format", "json"]
        assert main(args) == 0
        events = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
        assert any(e["type"] == "folder" and e["folderId"] == "f" for e in events)
        started = next(e for e in events if e["type"] == "run_started")
        assert started["descendantFolders"] == 1
        assert started["descendantPages"] == 2
        assert next(e for e in events if e["type"] == "summary")["wouldDownload"] == 2

    def test_download_never_exports_folder(self, monkeypatch, tmp_path):
        session = _patch(monkeypatch)
        assert main([URL, "--output", str(tmp_path)]) == 0
        exported = [u for u in session.urls if "exportword" in u]
        assert len(exported) == 2
        assert (tmp_path / "Acme Docs" / "Archive").is_dir()

    def test_excluded_folder_hidden_and_pruned(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        args = [URL, "--list-only", "--exclude", "archive", "--output", str(tmp_path)]
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "Archive" not in out and "Old page" not in out


FOLDER_URL = "https://x.atlassian.net/wiki/spaces/TEAM/folder/900/Infra"


class TestFolderRoot:
    def test_parse_folder_url(self):
        from confluence_word_export.urls import parse_root_url

        assert parse_root_url(FOLDER_URL) == (
            "https://x.atlassian.net",
            "900",
            "folder",
        )
        assert parse_root_url(URL)[2] == "page"

    def test_list_only_from_folder_root(self, monkeypatch, capsys, tmp_path):
        session = _patch(monkeypatch)
        assert main([FOLDER_URL, "--list-only", "--output", str(tmp_path)]) == 0
        out = capsys.readouterr().out
        assert "Infra/" in out and "Old page" in out
        assert any("/folders/900" in u for u in session.urls)
        assert any("/folders/900/descendants" in u for u in session.urls)

    def test_download_with_include_root_skips_folder_root(self, monkeypatch, tmp_path):
        session = _patch(monkeypatch)
        args = [FOLDER_URL, "--include-root", "--output", str(tmp_path)]
        assert main(args) == 0
        assert len([u for u in session.urls if "exportword" in u]) == 2
        assert (tmp_path / "Infra" / "Archive").is_dir()
