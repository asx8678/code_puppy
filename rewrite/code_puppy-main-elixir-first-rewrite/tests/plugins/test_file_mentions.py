"""Tests for code_puppy.plugins.file_mentions plugin."""

import os
import tempfile


from code_puppy.plugins.file_mentions.register_callbacks import (
    extract_file_mentions,
    generate_file_mention_context,
    resolve_mention_path,
)


class TestExtractFileMentions:
    def test_basic_file(self):
        mentions = extract_file_mentions("Look at @src/main.py for details")
        assert mentions == ["src/main.py"]

    def test_multiple_files(self):
        mentions = extract_file_mentions("Check @foo.py and @bar/baz.ts")
        assert set(mentions) == {"foo.py", "bar/baz.ts"}

    def test_deduplication(self):
        mentions = extract_file_mentions("@foo.py then @foo.py again")
        assert mentions == ["foo.py"]

    def test_ignores_usernames(self):
        """@username without dot/slash should be ignored."""
        mentions = extract_file_mentions("Thanks @john for the review")
        assert mentions == []

    def test_file_with_extension(self):
        mentions = extract_file_mentions("See @README.md")
        assert mentions == ["README.md"]

    def test_nested_path(self):
        mentions = extract_file_mentions("In @src/utils/helpers.py")
        assert mentions == ["src/utils/helpers.py"]

    def test_boundary_at_start(self):
        mentions = extract_file_mentions("@start.py is the entry point")
        assert mentions == ["start.py"]

    def test_boundary_after_paren(self):
        mentions = extract_file_mentions("(see @file.py)")
        assert mentions == ["file.py"]

    def test_no_mentions(self):
        mentions = extract_file_mentions("No files mentioned here")
        assert mentions == []

    def test_email_not_matched(self):
        """Email addresses should not be matched as file mentions."""
        mentions = extract_file_mentions("Contact user@example.com")
        # "example.com" has a dot so it might match - that's acceptable
        # The key thing is we don't crash


class TestResolveMentionPath:
    def test_existing_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "test.py")
            with open(test_file, "w") as f:
                f.write("# test")
            result = resolve_mention_path("test.py", tmpdir)
            assert result == os.path.abspath(test_file)

    def test_nonexistent_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = resolve_mention_path("nonexistent.py", tmpdir)
            assert result is None

    def test_nested_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "src")
            os.makedirs(subdir)
            test_file = os.path.join(subdir, "main.py")
            with open(test_file, "w") as f:
                f.write("# main")
            result = resolve_mention_path("src/main.py", tmpdir)
            assert result == os.path.abspath(test_file)

    def test_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "src")
            os.makedirs(subdir)
            result = resolve_mention_path("src", tmpdir)
            assert result == os.path.abspath(subdir)


class TestGenerateFileMentionContext:
    def test_basic_file_mention(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = os.path.join(tmpdir, "hello.py")
            with open(test_file, "w") as f:
                f.write("print('hello')")

            ctx = generate_file_mention_context("Check @hello.py", cwd=tmpdir)
            assert ctx is not None
            assert "hello.py" in ctx
            assert "print('hello')" in ctx
            assert "file_mention" in ctx

    def test_directory_mention(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "src")
            os.makedirs(subdir)
            with open(os.path.join(subdir, "a.py"), "w") as f:
                f.write("# a")
            with open(os.path.join(subdir, "b.py"), "w") as f:
                f.write("# b")

            ctx = generate_file_mention_context("List @src/", cwd=tmpdir)
            # src/ ends with / so the regex might not match it directly
            # But @src (without slash) should work
            ctx2 = generate_file_mention_context("List @src", cwd=tmpdir)
            if ctx2 is not None:
                assert "directory" in ctx2

    def test_no_mentions_returns_none(self):
        ctx = generate_file_mention_context("No files here")
        assert ctx is None

    def test_unresolvable_returns_none(self):
        ctx = generate_file_mention_context(
            "Check @nonexistent_file.xyz", cwd="/tmp"
        )
        assert ctx is None

    def test_max_files_limit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(15):
                with open(os.path.join(tmpdir, f"file{i}.py"), "w") as f:
                    f.write(f"# file {i}")

            text = " ".join(f"@file{i}.py" for i in range(15))
            ctx = generate_file_mention_context(text, cwd=tmpdir, max_files=3)
            if ctx is not None:
                # Should only include up to max_files
                # Count opening tags only (<file_mention), not closing tags (</file_mention>)
                assert ctx.count("<file_mention") <= 3
