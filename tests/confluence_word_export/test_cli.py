import json

import confluence_word_export.cli as cli_mod
from confluence_word_export.cli import main
from confluence_word_export.models import Auth

WORD_BODY = b"\xd0\xcf\x11\xe0" + b"\x00" * 300


class FakeResp:
    def __init__(
        self,
        status=200,
        json_data=None,
        headers=None,
        body=b"",
        url="https://x.atlassian.net",
    ):
        self.status_code = status
        self._json = json_data
        self.headers = headers or {}
        self._body = body
        self.history = []
        self.url = url

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class RoutingSession:
    """Routes GET calls based on URL/path to emulate the Confluence API + export."""

    def __init__(self):
        self.auth = None
        self.headers = {}

    def get(
        self, url, params=None, timeout=None, allow_redirects=True, stream=False, **kw
    ):
        if "/api/v2/pages/" in url and url.endswith("/descendants"):
            return FakeResp(
                json_data={
                    "results": [
                        {
                            "id": "111",
                            "title": "Team wiki",
                            "type": "page",
                            "parentId": "100",
                            "depth": 1,
                        },
                        {
                            "id": "222",
                            "title": "Authentication",
                            "type": "page",
                            "parentId": "111",
                            "depth": 2,
                        },
                        {
                            "id": "333",
                            "title": "Draft notes",
                            "type": "page",
                            "parentId": "100",
                            "depth": 1,
                        },
                        {
                            "id": "444",
                            "title": "Whiteboard",
                            "type": "whiteboard",
                            "parentId": "100",
                            "depth": 1,
                        },
                    ],
                    "_links": {},
                }
            )
        if "/api/v2/pages/" in url:
            return FakeResp(
                json_data={
                    "id": "100",
                    "title": "Acme Docs",
                    "parentId": None,
                }
            )
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
        raise AssertionError(f"unexpected URL {url}")


URL = "https://x.atlassian.net/wiki/spaces/TEAM/pages/100/Acme+Docs"


def _patch(monkeypatch):
    session = RoutingSession()
    monkeypatch.setattr(cli_mod, "load_auth", lambda: Auth("a@b.com", "tok"))
    monkeypatch.setattr(cli_mod, "enable_system_trust_store", lambda: True)

    def fake_build_session(auth, verify=None):
        session.verify = verify
        return session

    monkeypatch.setattr(cli_mod, "build_session", fake_build_session)
    # Isolate from any .confluence-word-export-ignore in the working directory so
    # CLI tests are deterministic regardless of where pytest is invoked.
    monkeypatch.setattr(cli_mod, "DEFAULT_IGNORE_FILE", "__no_such_ignore_file__")
    return session


class TestCliListOnly:
    def test_list_only_makes_no_export_calls(self, monkeypatch, capsys, tmp_path):
        session = _patch(monkeypatch)
        calls = []
        orig = session.get

        def spy(url, **kw):
            calls.append(url)
            return orig(url, **kw)

        session.get = spy
        code = main([URL, "--list-only", "--output", str(tmp_path)])
        out = capsys.readouterr().out
        assert code == 0
        assert "Acme Docs/" in out
        assert "Team wiki" in out
        assert not any("exportword" in c for c in calls)


class TestCliDownload:
    def test_full_download(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        code = main([URL, "--output", str(tmp_path)])
        out = capsys.readouterr().out
        assert code == 0
        # Root not selected by default; three descendant pages downloaded.
        assert "Downloaded:        3" in out
        root_dir = tmp_path / "Acme Docs"
        assert (root_dir / "page-111.doc").exists()
        assert (root_dir / "Team wiki" / "page-222.doc").exists()
        assert (root_dir / "page-333.doc").exists()

    def test_exclude_filter(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        code = main([URL, "--exclude", "draft", "--output", str(tmp_path)])
        capsys.readouterr()
        assert code == 0
        root_dir = tmp_path / "Acme Docs"
        # Draft notes excluded, but its (non-existent) children unaffected.
        assert not (root_dir / "page-333.doc").exists()
        assert (root_dir / "page-111.doc").exists()

    def test_exclude_prunes_subtree(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        # "Team wiki" (111) has child "Authentication" (222).
        code = main([URL, "--exclude", "wiki", "--output", str(tmp_path)])
        capsys.readouterr()
        assert code == 0
        root_dir = tmp_path / "Acme Docs"
        # Excluded parent: neither its file, its child, nor its folder appear.
        assert not (root_dir / "page-111.doc").exists()
        assert not (root_dir / "Team wiki").exists()
        assert not (root_dir / "Team wiki" / "page-222.doc").exists()
        # Unrelated sibling still downloads.
        assert (root_dir / "page-333.doc").exists()

    def test_rerun_skips_existing(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        main([URL, "--output", str(tmp_path)])
        capsys.readouterr()
        _patch(monkeypatch)
        code = main([URL, "--output", str(tmp_path)])
        out = capsys.readouterr().out
        assert code == 0
        assert "Skipped existing:  3" in out

    def test_include_root(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        code = main([URL, "--include-root", "--output", str(tmp_path)])
        capsys.readouterr()
        assert code == 0
        assert (tmp_path / "page-100.doc").exists()


class TestCliJsonFormat:
    def test_list_only_format_json(self, monkeypatch, capsys, tmp_path):
        _patch(monkeypatch)
        code = main([URL, "--list-only", "--output", str(tmp_path), "--format", "json"])
        out = capsys.readouterr().out
        assert code == 0
        lines = [json.loads(line) for line in out.splitlines() if line]
        assert lines[0]["type"] == "run_started"
        page_lines = lines[1:-1]
        assert all(line["type"] == "page" for line in page_lines)
        assert lines[-1]["type"] == "summary"
        page_ids = {line["pageId"] for line in page_lines}
        # Root not selected by default; no filters applied here.
        assert page_ids == {"111", "222", "333"}

    def test_download_format_json_emits_json_lines_and_nothing_else(
        self, monkeypatch, capsys, tmp_path
    ):
        _patch(monkeypatch)
        code = main([URL, "--output", str(tmp_path), "--format", "json"])
        out = capsys.readouterr().out
        assert code == 0
        lines = [json.loads(line) for line in out.splitlines() if line]
        types = [line["type"] for line in lines]
        assert types == ["run_started", "result", "result", "result", "summary"]
        assert lines[-1]["downloaded"] == 3
        statuses = {line["status"] for line in lines if line["type"] == "result"}
        assert statuses == {"DOWNLOADED"}

    def _statuses(self, monkeypatch, capsys, tmp_path, *filters):
        _patch(monkeypatch)
        code = main([URL, "--output", str(tmp_path), "--format", "json", *filters])
        out = capsys.readouterr().out
        assert code == 0
        lines = [json.loads(line) for line in out.splitlines() if line]
        statuses = {
            line["pageId"]: line["status"] for line in lines if line["type"] == "result"
        }
        return statuses, lines[0], lines[-1]

    def test_include_miss_reports_unselected(self, monkeypatch, capsys, tmp_path):
        # "Team wiki" (111) misses the include term but its child (222) matches.
        statuses, started, summary = self._statuses(
            monkeypatch, capsys, tmp_path, "--include", "authentication"
        )
        assert statuses == {
            "111": "UNSELECTED",
            "222": "DOWNLOADED",
            "333": "UNSELECTED",
        }
        assert started["unselectedPages"] == 2
        assert started["excludedPages"] == 0
        assert summary["unselected"] == 2
        assert summary["excluded"] == 0

    def test_exclude_term_reports_excluded_subtree(self, monkeypatch, capsys, tmp_path):
        statuses, started, summary = self._statuses(
            monkeypatch, capsys, tmp_path, "--exclude", "wiki"
        )
        assert statuses == {"111": "EXCLUDED", "222": "EXCLUDED", "333": "DOWNLOADED"}
        assert started["excludedPages"] == 2
        assert started["unselectedPages"] == 0
        assert summary["excluded"] == 2
        assert summary["unselected"] == 0

    def test_manifest_written_alongside_text_output(
        self, monkeypatch, capsys, tmp_path
    ):
        _patch(monkeypatch)
        manifest = tmp_path / "manifest.jsonl"
        code = main([URL, "--output", str(tmp_path), "--manifest", str(manifest)])
        out = capsys.readouterr().out
        assert code == 0
        # Human-readable text output is unaffected by --manifest.
        assert "DOWNLOADED" in out
        lines = [json.loads(line) for line in manifest.read_text().splitlines()]
        assert [line["type"] for line in lines] == [
            "run_started",
            "result",
            "result",
            "result",
            "summary",
        ]


class TestResolveVerify:
    def _args(self, **kw):
        import argparse

        ns = argparse.Namespace(ca_bundle=None, insecure=False)
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_default_is_none(self):
        assert cli_mod._resolve_verify(self._args()) is None

    def test_insecure_returns_false(self):
        assert cli_mod._resolve_verify(self._args(insecure=True)) is False

    def test_ca_bundle_returns_path(self, tmp_path):
        bundle = tmp_path / "ca.pem"
        bundle.write_text("cert", encoding="utf-8")
        assert cli_mod._resolve_verify(self._args(ca_bundle=str(bundle))) == str(bundle)

    def test_ca_bundle_missing_raises(self, tmp_path):
        import pytest

        from confluence_word_export.errors import UsageError

        with pytest.raises(UsageError):
            cli_mod._resolve_verify(self._args(ca_bundle=str(tmp_path / "nope.pem")))

    def test_both_options_conflict(self, tmp_path):
        import pytest

        from confluence_word_export.errors import UsageError

        bundle = tmp_path / "ca.pem"
        bundle.write_text("cert", encoding="utf-8")
        with pytest.raises(UsageError):
            cli_mod._resolve_verify(self._args(ca_bundle=str(bundle), insecure=True))

    def test_ca_bundle_sets_session_verify(self, monkeypatch, capsys, tmp_path):
        session = _patch(monkeypatch)
        bundle = tmp_path / "ca.pem"
        bundle.write_text("cert", encoding="utf-8")
        code = main(
            [URL, "--list-only", "--ca-bundle", str(bundle), "--output", str(tmp_path)]
        )
        assert code == 0
        assert session.verify == str(bundle)


class TestConfigureTls:
    def _args(self, **kw):
        import argparse

        ns = argparse.Namespace(
            ca_bundle=None, insecure=False, system_certs=False, no_system_certs=False
        )
        for k, v in kw.items():
            setattr(ns, k, v)
        return ns

    def test_default_enables_system_trust(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            cli_mod, "enable_system_trust_store", lambda: called.append(1) or True
        )
        assert cli_mod._configure_tls(self._args()) is None
        assert called == [1]

    def test_no_system_certs_skips_trust_store(self, monkeypatch):
        called = []
        monkeypatch.setattr(
            cli_mod, "enable_system_trust_store", lambda: called.append(1) or True
        )
        assert cli_mod._configure_tls(self._args(no_system_certs=True)) is None
        assert called == []

    def test_system_certs_requires_truststore(self, monkeypatch):
        import pytest

        from confluence_word_export.errors import UsageError

        monkeypatch.setattr(cli_mod, "enable_system_trust_store", lambda: False)
        with pytest.raises(UsageError):
            cli_mod._configure_tls(self._args(system_certs=True))

    def test_insecure_returns_false_and_warns(self, monkeypatch, capsys):
        monkeypatch.setattr(cli_mod, "enable_system_trust_store", lambda: True)
        assert cli_mod._configure_tls(self._args(insecure=True)) is False
        assert "disabled" in capsys.readouterr().err

    def test_ca_bundle_returns_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cli_mod, "enable_system_trust_store", lambda: True)
        bundle = tmp_path / "ca.pem"
        bundle.write_text("cert", encoding="utf-8")
        assert cli_mod._configure_tls(self._args(ca_bundle=str(bundle))) == str(bundle)

    def test_system_certs_conflicts_with_insecure(self):
        import pytest

        from confluence_word_export.errors import UsageError

        with pytest.raises(UsageError):
            cli_mod._configure_tls(self._args(system_certs=True, insecure=True))

    def test_system_and_no_system_conflict(self):
        import pytest

        from confluence_word_export.errors import UsageError

        with pytest.raises(UsageError):
            cli_mod._resolve_system_certs(
                self._args(system_certs=True, no_system_certs=True)
            )
