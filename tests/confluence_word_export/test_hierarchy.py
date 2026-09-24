from pathlib import Path

from confluence_word_export.hierarchy import build_hierarchy
from confluence_word_export.models import Page


def page(pid, title, parent, depth, pos=None):
    return Page(id=pid, title=title, parent_id=parent, depth=depth, child_position=pos)


ROOT = page("100", "Acme Docs", None, 0)


class TestHierarchy:
    def test_top_level_directory(self):
        placed = build_hierarchy(ROOT, [], Path("exports"))
        assert placed["100"].dir_path == Path("exports/Acme Docs")

    def test_child_placed_under_root(self):
        sec = page("111", "Team wiki", "100", 1)
        placed = build_hierarchy(ROOT, [sec], Path("exports"))
        p = placed["111"]
        assert p.parent_dir == Path("exports/Acme Docs")
        assert p.dir_path == Path("exports/Acme Docs/Team wiki")

    def test_grandchild_hierarchy(self):
        sec = page("111", "Team wiki", "100", 1)
        auth = page("222", "Authentication", "111", 2)
        placed = build_hierarchy(ROOT, [sec, auth], Path("exports"))
        assert placed["222"].parent_dir == Path("exports/Acme Docs/Team wiki")

    def test_has_children_flag(self):
        sec = page("111", "Team wiki", "100", 1)
        auth = page("222", "Authentication", "111", 2)
        placed = build_hierarchy(ROOT, [sec, auth], Path("exports"))
        assert placed["111"].has_children is True
        assert placed["222"].has_children is False

    def test_excluded_ancestor_still_has_directory(self):
        draft = page("111", "Draft standards", "100", 1)
        approved = page("222", "Approved security standard", "111", 2)
        placed = build_hierarchy(ROOT, [draft, approved], Path("exports"))
        # The path for the approved page still reflects Draft standards.
        assert "Draft standards" in str(placed["222"].parent_dir)

    def test_sibling_collision_uses_page_id(self):
        a = page("201", "Security guidance", "100", 1, pos=0)
        b = page("202", "Security guidance", "100", 1, pos=1)
        placed = build_hierarchy(ROOT, [a, b], Path("exports"))
        names = {placed["201"].base_name, placed["202"].base_name}
        assert "Security guidance" in names
        assert "Security guidance - 202" in names

    def test_orphan_attaches_to_root(self):
        orphan = page("999", "Orphan", "does-not-exist", 3)
        placed = build_hierarchy(ROOT, [orphan], Path("exports"))
        assert placed["999"].parent_dir == placed["100"].dir_path

    def test_deterministic_across_runs(self):
        a = page("201", "Dup", "100", 1, pos=0)
        b = page("202", "Dup", "100", 1, pos=1)
        first = build_hierarchy(ROOT, [a, b], Path("exports"))
        second = build_hierarchy(ROOT, [b, a], Path("exports"))
        assert first["201"].base_name == second["201"].base_name
        assert first["202"].base_name == second["202"].base_name
