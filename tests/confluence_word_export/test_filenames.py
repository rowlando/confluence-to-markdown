from confluence_word_export.filenames import (
    add_collision_suffix,
    extension_for_content_type,
    parse_content_disposition,
    sanitise_name,
)


class TestSanitiseName:
    def test_removes_path_separators(self):
        assert "/" not in sanitise_name("a/b")
        assert "\\" not in sanitise_name("a\\b")

    def test_removes_invalid_chars(self):
        out = sanitise_name('a<b>c:d"e|f?g*h')
        for ch in '<>:"|?*':
            assert ch not in out

    def test_removes_null(self):
        assert "\x00" not in sanitise_name("a\x00b")

    def test_dot_segments(self):
        assert sanitise_name(".") == "untitled"
        assert sanitise_name("..") == "untitled"

    def test_trailing_dots_spaces(self):
        assert not sanitise_name("name.  ").endswith((" ", "."))

    def test_length_cap(self):
        assert len(sanitise_name("x" * 500)) <= 180

    def test_reserved_name(self):
        assert sanitise_name("CON").lower() != "con"

    def test_keeps_readable_title(self):
        assert sanitise_name("Acme Docs") == "Acme Docs"


class TestCollision:
    def test_suffix_before_extension(self):
        assert (
            add_collision_suffix("Security guidance.doc", "123")
            == "Security guidance - 123.doc"
        )

    def test_suffix_directory(self):
        assert (
            add_collision_suffix("Security guidance", "123")
            == "Security guidance - 123"
        )


class TestContentDisposition:
    def test_plain_filename(self):
        assert (
            parse_content_disposition(
                'attachment; filename="Authentication guidance.doc"'
            )
            == "Authentication guidance.doc"
        )

    def test_unquoted_filename(self):
        assert (
            parse_content_disposition("attachment; filename=report.doc") == "report.doc"
        )

    def test_extended_filename_precedence(self):
        header = "attachment; filename=\"fallback.doc\"; filename*=UTF-8''Aud%C3%ADt%20log.doc"
        assert parse_content_disposition(header) == "Audít log.doc"

    def test_none(self):
        assert parse_content_disposition(None) is None
        assert parse_content_disposition("attachment") is None

    def test_strips_path_components(self):
        assert (
            parse_content_disposition('attachment; filename="../../etc/passwd"')
            == "passwd"
        )


class TestContentTypeExtension:
    def test_doc(self):
        assert extension_for_content_type("application/msword") == ".doc"

    def test_docx(self):
        assert (
            extension_for_content_type(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document; charset=utf-8"
            )
            == ".docx"
        )

    def test_unknown(self):
        assert extension_for_content_type("text/html") is None
        assert extension_for_content_type(None) is None
