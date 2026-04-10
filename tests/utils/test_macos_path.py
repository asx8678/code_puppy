"""Tests for code_puppy.utils.macos_path."""

import os
import sys
import unicodedata
import pytest
from code_puppy.utils.macos_path import resolve_path_with_variants


class TestResolvePathWithVariants:
    """Tests for macOS path variant resolution."""

    def test_existing_file_returns_immediately(self, tmp_path):
        """If the file exists at the original path, return it unchanged."""
        target = tmp_path / "test.txt"
        target.write_text("content")
        result = resolve_path_with_variants(str(target))
        assert result == str(target)

    def test_nonexistent_file_returns_original(self, tmp_path):
        """If no variant matches, return the original path."""
        result = resolve_path_with_variants(str(tmp_path / "nope.txt"))
        assert result == str(tmp_path / "nope.txt")

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only test")
    def test_nfd_variant_resolves(self, tmp_path):
        """NFD-encoded filename on disk resolves from NFC input."""
        # Create file with NFD name (decomposed é = e + combining accent)
        nfd_name = unicodedata.normalize("NFD", "café.txt")
        nfd_path = tmp_path / nfd_name
        nfd_path.write_text("content")

        # Try to resolve with NFC name (composed é)
        nfc_name = unicodedata.normalize("NFC", "café.txt")
        nfc_path = str(tmp_path / nfc_name)

        result = resolve_path_with_variants(nfc_path)
        assert os.path.exists(result)

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only test")
    def test_narrow_nbsp_screenshot_variant(self, tmp_path):
        """Screenshot with narrow NBSP resolves from regular space."""
        # Create file with narrow no-break space before PM
        narrow_nbsp = "\u202f"
        real_name = f"Screenshot 2024-01-15 at 2.30.15{narrow_nbsp}PM.png"
        real_path = tmp_path / real_name
        real_path.write_text("image data")

        # Try with regular space (what LLM outputs)
        llm_name = "Screenshot 2024-01-15 at 2.30.15 PM.png"
        llm_path = str(tmp_path / llm_name)

        result = resolve_path_with_variants(llm_path)
        assert os.path.exists(result)

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only test")
    def test_curly_quote_variant(self, tmp_path):
        """File with curly quote resolves from straight quote."""
        curly = "\u2019"
        real_name = f"l{curly}exemple.txt"
        real_path = tmp_path / real_name
        real_path.write_text("content")

        llm_name = "l'exemple.txt"
        llm_path = str(tmp_path / llm_name)

        result = resolve_path_with_variants(llm_path)
        assert os.path.exists(result)

    @pytest.mark.skipif(sys.platform != "darwin", reason="macOS-only test")
    def test_combined_nfd_and_curly_quote(self, tmp_path):
        """Combined NFD + curly quote resolves."""
        curly = "\u2019"
        nfd_name = unicodedata.normalize("NFD", f"l{curly}éxample.txt")
        real_path = tmp_path / nfd_name
        real_path.write_text("content")

        # LLM uses NFC + straight quote
        llm_name = "l'éxample.txt"
        llm_path = str(tmp_path / llm_name)

        result = resolve_path_with_variants(llm_path)
        assert os.path.exists(result)

    def test_non_macos_skips_variants(self, tmp_path, monkeypatch):
        """On non-macOS, variants are skipped entirely."""
        monkeypatch.setattr(sys, "platform", "linux")
        result = resolve_path_with_variants(str(tmp_path / "nope.txt"))
        assert result == str(tmp_path / "nope.txt")

    def test_unicode_space_normalization(self, tmp_path):
        """Non-breaking spaces are normalized to regular spaces."""
        # Create file with regular space
        real_path = tmp_path / "my file.txt"
        real_path.write_text("content")

        if sys.platform != "darwin":
            pytest.skip("macOS-only test")

        # Try with non-breaking space
        nbsp_path = str(tmp_path / "my\u00a0file.txt")
        result = resolve_path_with_variants(nbsp_path)
        assert os.path.exists(result)
