from confluence_word_export.filters import (
    build_decisions,
    decide,
    filter_pages,
    load_ignore_terms,
)
from confluence_word_export.models import (
    OUTCOME_EXCLUDED,
    OUTCOME_SELECTED,
    OUTCOME_UNSELECTED,
    Page,
)


def make_page(pid, title, parent=None, depth=1, pos=None):
    return Page(id=pid, title=title, parent_id=parent, depth=depth, child_position=pos)


class TestIgnoreFile:
    def test_parses_terms_skipping_comments_and_blanks(self, tmp_path):
        f = tmp_path / "ignore"
        f.write_text("# comment\n\ndraft\n  archive  \nDRAFT\n", encoding="utf-8")
        terms = load_ignore_terms(f, explicit=True)
        assert terms == ["draft", "archive"]  # deduped case-insensitively

    def test_terms_are_lowercased(self, tmp_path):
        f = tmp_path / "ignore"
        f.write_text("SPIKE\nWIP\nFurther Support\n", encoding="utf-8")
        terms = load_ignore_terms(f, explicit=True)
        assert terms == ["spike", "wip", "further support"]

    def test_missing_default_is_silent(self, tmp_path):
        assert load_ignore_terms(tmp_path / "nope", explicit=False) == []

    def test_missing_explicit_raises(self, tmp_path):
        import pytest

        from confluence_word_export.errors import UsageError

        with pytest.raises(UsageError):
            load_ignore_terms(tmp_path / "nope", explicit=True)

    def test_none_path(self):
        assert load_ignore_terms(None, explicit=False) == []


class TestFiltering:
    def test_no_include_matches_all(self):
        d = decide("Anything", [], [])
        assert d.selected

    def test_include_or_semantics(self):
        assert decide("security guidance", ["security", "architecture"], []).selected
        assert decide("architecture notes", ["security", "architecture"], []).selected
        assert not decide("random", ["security", "architecture"], []).selected

    def test_exclude_overrides_include(self):
        d = decide("Draft security guidance", ["security"], ["draft"])
        assert d.outcome == OUTCOME_EXCLUDED

    def test_include_miss_is_unselected_not_excluded(self):
        d = decide("random", ["security"], [])
        assert d.outcome == OUTCOME_UNSELECTED

    def test_match_is_selected(self):
        assert decide("security", ["security"], []).outcome == OUTCOME_SELECTED

    def test_case_insensitive_substring(self):
        assert not decide("Architecture guidance — DRAFT", [], ["draft"]).selected
        assert not decide("Architecture Archive", [], ["archive"]).selected

    def test_filter_pages(self):
        pages = [
            make_page("1", "Security overview"),
            make_page("2", "Draft security notes"),
            make_page("3", "Cooking"),
        ]
        kept = filter_pages(pages, ["security"], ["draft"])
        assert [p.id for p in kept] == ["1"]

    def test_build_decisions_keys(self):
        pages = [make_page("1", "A"), make_page("2", "B")]
        decisions = build_decisions(pages, [], [])
        assert set(decisions) == {"1", "2"}

    def test_exclude_term_prunes_descendants(self):
        pages = [
            make_page("root", "Root", parent=None, depth=0),
            make_page("arch", "Archived", parent="root", depth=1),
            make_page("child", "Live guidance", parent="arch", depth=2),
            make_page("grand", "Deep note", parent="child", depth=3),
            make_page("keep", "Current work", parent="root", depth=1),
        ]
        decisions = build_decisions(pages, [], ["archived"])
        assert decisions["arch"].outcome == OUTCOME_EXCLUDED
        assert decisions["child"].outcome == OUTCOME_EXCLUDED  # pruned via ancestor
        assert decisions["grand"].outcome == OUTCOME_EXCLUDED  # pruned via ancestor
        assert decisions["keep"].selected

    def test_include_miss_does_not_prune_descendants(self):
        pages = [
            make_page("root", "Root", parent=None, depth=0),
            make_page("parent", "Misc", parent="root", depth=1),
            make_page("child", "Security notes", parent="parent", depth=2),
        ]
        decisions = build_decisions(pages, ["security"], [])
        assert decisions["parent"].outcome == OUTCOME_UNSELECTED  # include miss
        assert decisions["child"].selected  # still matched, not pruned
