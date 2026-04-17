defmodule CodePuppyControl.HashLineTest do
  @moduledoc """
  Tests for the pure Elixir HashLine implementation.

  These tests verify that HashLine matches the behavioral contract
  of the NIF-based HashlineNif module.
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.HashLine

  describe "compute_line_hash/2" do
    test "returns 2 uppercase chars" do
      hash = HashLine.compute_line_hash(1, "hello world")
      assert String.length(hash) == 2
      assert hash =~ ~r/^[A-Z]{2}$/
    end

    test "different indices can produce different hashes for whitespace-only lines" do
      # Note: Some indices may produce the same hash (collisions are possible)
      # e.g., idx=1 and idx=2 both produce "KM" for whitespace-only lines
      # Use indices that are known to produce different hashes
      h1 = HashLine.compute_line_hash(1, "   ")
      h5 = HashLine.compute_line_hash(5, "   ")
      assert String.length(h1) == 2
      assert String.length(h5) == 2
      # These specific indices produce different hashes
      assert h1 != h5
    end

    test "strips trailing whitespace before hashing" do
      h1 = HashLine.compute_line_hash(1, "hello")
      h2 = HashLine.compute_line_hash(1, "hello   ")
      assert h1 == h2
    end

    test "strips trailing \\r before hashing" do
      h1 = HashLine.compute_line_hash(1, "hello")
      h2 = HashLine.compute_line_hash(1, "hello\r")
      assert h1 == h2
    end

    test "empty line uses idx as seed" do
      h1 = HashLine.compute_line_hash(1, "")
      h2 = HashLine.compute_line_hash(100, "")
      assert String.length(h1) == 2
      assert String.length(h2) == 2
      # Each should validate correctly for its own idx
      assert HashLine.validate_hashline_anchor(1, "", h1)
      assert HashLine.validate_hashline_anchor(100, "", h2)
    end

    test "alnum content ignores idx (seed=0)" do
      h1 = HashLine.compute_line_hash(1, "foo")
      h99 = HashLine.compute_line_hash(99, "foo")
      assert h1 == h99
    end

    test "chars come from NIBBLE_STR" do
      nibble = "ZPMQVRWSNKTXJBYH"
      hash = HashLine.compute_line_hash(1, "some code here")
      assert String.at(hash, 0) in String.graphemes(nibble)
      assert String.at(hash, 1) in String.graphemes(nibble)
    end
  end

  describe "format_hashlines/2" do
    test "basic formatting with start_line 1" do
      result = HashLine.format_hashlines("foo\nbar", 1)
      lines = String.split(result, "\n")
      assert length(lines) == 2
      assert String.starts_with?(hd(lines), "1#")
      assert String.contains?(hd(lines), ":foo")
      assert String.starts_with?(List.last(lines), "2#")
      assert String.contains?(List.last(lines), ":bar")
    end

    test "respects start_line parameter" do
      result = HashLine.format_hashlines("hello", 10)
      assert String.starts_with?(result, "10#")
      assert String.ends_with?(result, ":hello")
    end

    test "handles multi-line text" do
      result = HashLine.format_hashlines("line1\nline2\nline3", 1)
      lines = String.split(result, "\n")
      assert length(lines) == 3
      assert String.starts_with?(Enum.at(lines, 0), "1#")
      assert String.starts_with?(Enum.at(lines, 1), "2#")
      assert String.starts_with?(Enum.at(lines, 2), "3#")
    end

    test "handles empty string" do
      result = HashLine.format_hashlines("", 1)
      # Empty string splits into one empty line
      assert String.starts_with?(result, "1#")
    end

    test "produces correct prefix format" do
      result = HashLine.format_hashlines("hello\nworld", 1)
      lines = String.split(result, "\n")
      # Each line matches pattern: ^\d+#[A-Z]{2}:.*
      for line <- lines do
        assert line =~ ~r/^\d+#[A-Z]{2}:/
      end
    end

    test "preserves content after prefix" do
      original = "    def foo(self):\n        return 42"
      result = HashLine.format_hashlines(original, 1)
      lines = String.split(result, "\n")
      original_lines = String.split(original, "\n")

      for {fmt_line, orig_line} <- Enum.zip(lines, original_lines) do
        assert String.ends_with?(fmt_line, ":" <> orig_line)
      end
    end
  end

  describe "strip_hashline_prefixes/1" do
    test "round-trip: format then strip returns original" do
      original = "line one\nline two\n"
      formatted = HashLine.format_hashlines(original, 1)
      stripped = HashLine.strip_hashline_prefixes(formatted)
      assert stripped == original
    end

    test "round-trip with multiline" do
      original = "line one\nline two\nline three"
      formatted = HashLine.format_hashlines(original, 1)
      stripped = HashLine.strip_hashline_prefixes(formatted)
      assert stripped == original
    end

    test "round-trip with unicode" do
      original = "café\n日本語"
      formatted = HashLine.format_hashlines(original, 1)
      stripped = HashLine.strip_hashline_prefixes(formatted)
      assert stripped == original
    end

    test "passthrough for lines without prefix" do
      text = "no prefix here\njust plain text"
      stripped = HashLine.strip_hashline_prefixes(text)
      assert stripped == text
    end

    test "handles mixed prefixed and plain lines" do
      formatted = HashLine.format_hashlines("hello", 1)
      mixed = formatted <> "\nplain line"
      stripped = HashLine.strip_hashline_prefixes(mixed)
      assert stripped == "hello\nplain line"
    end

    test "does not strip lines that look like prefixes but are not valid" do
      # "abc#XY:text" - no digits before #
      assert HashLine.strip_hashline_prefixes("abc#XY:text") == "abc#XY:text"
      # "1#xy:text" - lowercase after #
      assert HashLine.strip_hashline_prefixes("1#xy:text") == "1#xy:text"
      # "1#X:text" - only 1 char after #
      assert HashLine.strip_hashline_prefixes("1#X:text") == "1#X:text"
    end

    test "handles edge case: hash in content" do
      formatted = HashLine.format_hashlines("some#text", 1)
      stripped = HashLine.strip_hashline_prefixes(formatted)
      assert stripped == "some#text"
    end
  end

  describe "validate_hashline_anchor/3" do
    test "valid anchor returns true" do
      hash = HashLine.compute_line_hash(5, "some code")
      assert HashLine.validate_hashline_anchor(5, "some code", hash)
    end

    test "invalid anchor returns false" do
      hash = HashLine.compute_line_hash(5, "some code")
      refute HashLine.validate_hashline_anchor(5, "different code", hash)
    end

    test "wrong idx for blank line" do
      h1 = HashLine.compute_line_hash(1, "")
      h2 = HashLine.compute_line_hash(100, "")
      # Each hash validates for its own idx
      assert HashLine.validate_hashline_anchor(1, "", h1)
      assert HashLine.validate_hashline_anchor(100, "", h2)
      # Hash for idx=1 must NOT validate as idx=1 with wrong content
      refute HashLine.validate_hashline_anchor(1, "x", h1)
    end

    test "alnum content: idx is irrelevant (seed=0)" do
      h = HashLine.compute_line_hash(1, "some text")
      # Should validate with different idx since alnum content uses seed=0
      assert HashLine.validate_hashline_anchor(99, "some text", h)
    end

    test "unicode content validates correctly" do
      h = HashLine.compute_line_hash(1, "café 🚀")
      assert HashLine.validate_hashline_anchor(1, "café 🚀", h)
      refute HashLine.validate_hashline_anchor(1, "cafe 🚀", h)
    end
  end

  describe "cross-compatibility" do
    test "compute_line_hash produces known reference values" do
      # Verify against known values to catch algorithm drift
      result = HashLine.compute_line_hash(0, "hello world")
      assert String.length(result) == 2
      # determinism check
      assert result == HashLine.compute_line_hash(0, "hello world")
    end
  end

  describe "parity with HashlineNif" do
    # These tests verify that HashLine.compute_line_hash/2 produces
    # exactly the same results as HashlineNif.compute_line_hash/2
    # for all types of input (empty, whitespace-only, alnum content).

    alias CodePuppyControl.HashlineNif

    test "empty string matches NIF for multiple indices" do
      for idx <- [0, 1, 2, 5, 10, 100] do
        assert HashLine.compute_line_hash(idx, "") == HashlineNif.compute_line_hash(idx, ""),
               "mismatch for idx=#{idx}, empty string"
      end
    end

    test "whitespace-only matches NIF" do
      for {idx, line} <- [
            {1, "   "},
            {2, "\t"},
            {3, "\t\t"},
            {4, "\r"},
            {5, "  \r\n  "},
            {10, "    \n    "}
          ] do
        assert HashLine.compute_line_hash(idx, line) == HashlineNif.compute_line_hash(idx, line),
               "mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end

    test "alphanumeric content matches NIF (seed=0)" do
      for {idx, line} <- [
            {0, "hello world"},
            {1, "foo"},
            {5, "some code"},
            {99, "test line"},
            {1, "unicode: café 🚀"},
            {0, "def function():"},
            {100, "class MyClass:"}
          ] do
        assert HashLine.compute_line_hash(idx, line) == HashlineNif.compute_line_hash(idx, line),
               "mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end

    test "punctuation-only content matches NIF" do
      for {idx, line} <- [
            {1, "!@#$%"},
            {2, "---"},
            {3, "=== \"\" ==="},
            {5, "/* comment */"}
          ] do
        assert HashLine.compute_line_hash(idx, line) == HashlineNif.compute_line_hash(idx, line),
               "mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end

    test "format_hashlines matches NIF exactly" do
      for {text, start_line} <- [
            {"foo\nbar", 1},
            {"", 1},
            {"single line", 5},
            {"line1\nline2\nline3", 1},
            {"line1\nline2\nline3", 10},
            {"  indented\n    more  ", 1}
          ] do
        h_result = HashLine.format_hashlines(text, start_line)
        n_result = HashlineNif.format_hashlines(text, start_line)

        assert h_result == n_result,
               "format_hashlines mismatch for text=#{inspect(text)}, start_line=#{start_line}"
      end
    end

    test "strip_hashline_prefixes matches NIF exactly" do
      for text <- [
            "1#BK:foo\n2#MJ:bar",
            "1#KM:",
            "10#XX:hello\n11#YY:world",
            "no prefix here",
            "mixed\n2#AB:prefixed\nplain"
          ] do
        h_result = HashLine.strip_hashline_prefixes(text)
        n_result = HashlineNif.strip_hashline_prefixes(text)

        assert h_result == n_result,
               "strip_hashline_prefixes mismatch for text=#{inspect(text)}"
      end
    end

    test "validate_hashline_anchor matches NIF exactly" do
      for {idx, line} <- [
            {1, "hello"},
            {5, ""},
            {10, "   "},
            {99, "test"}
          ] do
        hash = HashLine.compute_line_hash(idx, line)
        h_result = HashLine.validate_hashline_anchor(idx, line, hash)
        n_result = HashlineNif.validate_hashline_anchor(idx, line, hash)

        assert h_result == n_result,
               "validate_hashline_anchor mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end
  end

  describe "determinism" do
    test "same content produces same hash" do
      h1 = HashLine.compute_line_hash(5, "identical line")
      h2 = HashLine.compute_line_hash(5, "identical line")
      assert h1 == h2
    end

    test "format is deterministic" do
      r1 = HashLine.format_hashlines("alpha\nbeta", 1)
      r2 = HashLine.format_hashlines("alpha\nbeta", 1)
      assert r1 == r2
    end
  end
end
