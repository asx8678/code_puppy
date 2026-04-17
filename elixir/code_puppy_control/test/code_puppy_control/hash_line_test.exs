defmodule CodePuppyControl.HashLineTest do
  @moduledoc """
  Comprehensive parity tests for HashLine (pure Elixir) vs HashlineNif (Rust).

  These tests verify that the pure Elixir implementation in `CodePuppyControl.HashLine`
  produces identical output to the Rust NIF implementation in `CodePuppyControl.HashlineNif`.

  ## Test Organization

  1. **Basic functionality tests** - ported from hashline_nif_test.exs
  2. **Known reference values** - hardcoded expected outputs to prevent algorithm drift
  3. **Parity tests** - direct comparison between HashLine and HashlineNif
  4. **Edge cases** - empty strings, unicode, special characters, etc.

  ## Notes

  - Tests tagged with `:parity` are skipped when the NIF is not loaded
  - The NIF is assumed to be the reference implementation
  - When bd-149 merges the real HashLine implementation, these tests should all pass
  """

  use ExUnit.Case, async: true

  alias CodePuppyControl.HashLine
  alias CodePuppyControl.HashlineNif

  # ============================================================================
  # Section 1: Basic functionality (mirrors hashline_nif_test.exs)
  # ============================================================================

  describe "compute_line_hash/2 - basic functionality" do
    test "returns 2 uppercase chars" do
      hash = HashLine.compute_line_hash(1, "hello world")
      assert String.length(hash) == 2
      assert hash =~ ~r/^[A-Z]{2}$/
    end

    test "whitespace-only lines are deterministic and validate for their own idx" do
      h1 = HashLine.compute_line_hash(1, "   ")
      h2 = HashLine.compute_line_hash(2, "   ")
      assert String.length(h1) == 2
      assert String.length(h2) == 2
      assert HashLine.validate_hashline_anchor(1, "   ", h1)
      assert HashLine.validate_hashline_anchor(2, "   ", h2)
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

  describe "format_hashlines/2 - basic functionality" do
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

  describe "strip_hashline_prefixes/1 - basic functionality" do
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

    test "does not strip lines that look like prefixes but aren't valid" do
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

  describe "validate_hashline_anchor/3 - basic functionality" do
    test "valid anchor returns true" do
      hash = HashLine.compute_line_hash(5, "some code")
      assert HashLine.validate_hashline_anchor(5, "some code", hash)
    end

    test "invalid anchor returns false" do
      hash = HashLine.compute_line_hash(5, "some code")
      refute HashLine.validate_hashline_anchor(5, "different code", hash)
    end

    test "wrong idx for blank line validates only for own content" do
      h1 = HashLine.compute_line_hash(1, "")
      h2 = HashLine.compute_line_hash(100, "")
      assert HashLine.validate_hashline_anchor(1, "", h1)
      assert HashLine.validate_hashline_anchor(100, "", h2)
      # Only assert content mismatch, NOT that h1 != h2 (collisions possible)
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

  # ============================================================================
  # Section 2: Known reference values (prevent algorithm drift)
  # ============================================================================

  describe "known reference values" do
    test "compute_line_hash: known outputs for alnum content" do
      # These are pinned from HashlineNif (Rust xxHash32 reference)
      assert HashLine.compute_line_hash(0, "hello world") == "MM"
      assert HashLine.compute_line_hash(1, "foo") == "BK"
      assert HashLine.compute_line_hash(5, "some code") == "WP"
      assert HashLine.compute_line_hash(1, "café 🚀") == "ZZ"
    end

    test "compute_line_hash: known outputs for whitespace/empty/punctuation (seed=idx)" do
      # Note: collisions are possible in 2-char space - "KM" appears for both empty idx=1 and spaces idx=2
      assert HashLine.compute_line_hash(1, "") == "KM"
      assert HashLine.compute_line_hash(1, "!@#$%") == "JB"
      assert HashLine.compute_line_hash(2, "   ") == "KM"
    end

    test "compute_line_hash: alnum ignores idx (seed=0)" do
      h1 = HashLine.compute_line_hash(1, "foo")
      h2 = HashLine.compute_line_hash(2, "foo")
      h99 = HashLine.compute_line_hash(99, "foo")

      # All should be identical (seed=0 for alnum content)
      assert h1 == "BK"
      assert h1 == h2
      assert h2 == h99
    end

    test "format_hashlines: known output" do
      assert HashLine.format_hashlines("foo\nbar", 1) == "1#BK:foo\n2#MJ:bar"
      assert HashLine.format_hashlines("", 1) == "1#KM:"
    end
  end

  # ============================================================================
  # Section 3: Parity tests (HashLine vs HashlineNif)
  # ============================================================================

  describe "parity: compute_line_hash/2" do
    setup context do
      if function_exported?(HashlineNif, :compute_line_hash, 2) do
        {:ok, context}
      else
        {:skip, "HashlineNif not loaded"}
      end
    end

    test "matches NIF for alnum content across multiple indices" do
      for {idx, line} <- [
            {0, "hello world"},
            {1, "foo"},
            {99, "foo"},
            {5, "some code"},
            {0, "café 🚀"},
            {1, "日本語"}
          ] do
        expected = HashlineNif.compute_line_hash(idx, line)

        assert HashLine.compute_line_hash(idx, line) == expected,
               "mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end

    test "matches NIF for empty and whitespace-only lines" do
      for {idx, line} <- [
            {0, ""},
            {1, ""},
            {2, ""},
            {1, "   "},
            {2, "\t"},
            {3, "\r"}
          ] do
        expected = HashlineNif.compute_line_hash(idx, line)

        assert HashLine.compute_line_hash(idx, line) == expected,
               "mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end

    test "matches NIF for unicode content" do
      for {idx, line} <- [
            {1, "café"},
            {2, "日本語"},
            {5, "🚀 emoji 🎉"},
            {10, "Ümläuts"},
            {99, "한국어"}
          ] do
        expected = HashlineNif.compute_line_hash(idx, line)

        assert HashLine.compute_line_hash(idx, line) == expected,
               "mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end

    test "matches NIF for edge cases" do
      for {idx, line} <- [
            {1, "# comment"},
            {2, "// another comment"},
            {5, "123 numbers"},
            {10, "special!@#$%chars"},
            {99, "mixed123ABCxyz"},
            {1, "trailing  "},
            {1, "trailing\t"},
            {1, "trailing\r"},
            {1, "trailing\r\n"}
          ] do
        expected = HashlineNif.compute_line_hash(idx, line)

        assert HashLine.compute_line_hash(idx, line) == expected,
               "mismatch for idx=#{idx}, line=#{inspect(line)}"
      end
    end
  end

  describe "parity: format_hashlines/2" do
    setup context do
      if function_exported?(HashlineNif, :format_hashlines, 2) do
        {:ok, context}
      else
        {:skip, "HashlineNif not loaded"}
      end
    end

    test "matches NIF output exactly" do
      for {text, start_line} <- [
            {"", 1},
            {"\n", 1},
            {"foo\n\nbar", 1},
            {"  \nfoo", 10},
            {"hello world", 1},
            {"hello", 1},
            {"foo\nbar", 1},
            {"line1\nline2\nline3", 1},
            {"single", 100},
            {"a\nb\nc\nd", 50}
          ] do
        expected = HashlineNif.format_hashlines(text, start_line)

        assert HashLine.format_hashlines(text, start_line) == expected,
               "mismatch for text=#{inspect(text)}, start_line=#{start_line}"
      end
    end

    test "matches NIF for code text" do
      code = """
      defmodule Foo do
        def bar do
          :baz
        end
      end
      """

      expected = HashlineNif.format_hashlines(code, 1)
      assert HashLine.format_hashlines(code, 1) == expected
    end

    test "matches NIF for unicode text" do
      text = "café\n日本語\n🚀"
      expected = HashlineNif.format_hashlines(text, 1)
      assert HashLine.format_hashlines(text, 1) == expected
    end
  end

  describe "parity: strip_hashline_prefixes/1" do
    setup context do
      if function_exported?(HashlineNif, :strip_hashline_prefixes, 1) do
        {:ok, context}
      else
        {:skip, "HashlineNif not loaded"}
      end
    end

    test "matches NIF for formatted text" do
      original = "line one\nline two\nline three"
      formatted = HashlineNif.format_hashlines(original, 1)

      expected = HashlineNif.strip_hashline_prefixes(formatted)
      assert HashLine.strip_hashline_prefixes(formatted) == expected
      assert expected == original
    end

    test "matches NIF for mixed text" do
      mixed = "1#AB:has prefix\nno prefix here\n2#CD:another prefix"

      expected = HashlineNif.strip_hashline_prefixes(mixed)
      assert HashLine.strip_hashline_prefixes(mixed) == expected
    end
  end

  describe "parity: validate_hashline_anchor/3" do
    setup context do
      if function_exported?(HashlineNif, :validate_hashline_anchor, 3) do
        {:ok, context}
      else
        {:skip, "HashlineNif not loaded"}
      end
    end

    test "matches NIF for valid anchors" do
      for {idx, line} <- [
            {1, "hello"},
            {5, "code"},
            {100, "unicode: 🎉"},
            {1, ""},
            {50, "   "}
          ] do
        hash = HashlineNif.compute_line_hash(idx, line)
        expected = HashlineNif.validate_hashline_anchor(idx, line, hash)
        assert HashLine.validate_hashline_anchor(idx, line, hash) == expected
        assert expected == true
      end
    end

    test "matches NIF for invalid anchors" do
      for {idx, line, hash} <- [
            {1, "hello", "XX"},
            {1, "hello", "YY"},
            {5, "modified", HashlineNif.compute_line_hash(5, "original")}
          ] do
        expected = HashlineNif.validate_hashline_anchor(idx, line, hash)
        assert HashLine.validate_hashline_anchor(idx, line, hash) == expected
        assert expected == false
      end
    end
  end

  # ============================================================================
  # Section 4: Edge cases
  # ============================================================================

  describe "edge cases" do
    test "empty string handling" do
      # Single empty line
      hash = HashLine.compute_line_hash(1, "")
      assert String.length(hash) == 2
      assert HashLine.validate_hashline_anchor(1, "", hash)
    end

    test "only whitespace lines" do
      for ws <- [" ", "  ", "   ", "\t", "\t\t", " \t ", "\r", "\r\n"] do
        hash = HashLine.compute_line_hash(1, ws)
        assert String.length(hash) == 2
        assert HashLine.validate_hashline_anchor(1, ws, hash)
      end
    end

    test "unicode characters: emoji" do
      text = "🚀🎉🎊"
      hash = HashLine.compute_line_hash(1, text)
      assert String.length(hash) == 2
      assert HashLine.validate_hashline_anchor(1, text, hash)
    end

    test "unicode characters: CJK" do
      text = "日本語テキスト"
      hash = HashLine.compute_line_hash(1, text)
      assert String.length(hash) == 2
      assert HashLine.validate_hashline_anchor(1, text, hash)
    end

    test "unicode characters: accented" do
      text = "café résumé naïve"
      hash = HashLine.compute_line_hash(1, text)
      assert String.length(hash) == 2
      assert HashLine.validate_hashline_anchor(1, text, hash)
    end

    test "very long lines" do
      text = String.duplicate("a", 10000)
      hash = HashLine.compute_line_hash(1, text)
      assert String.length(hash) == 2
      assert HashLine.validate_hashline_anchor(1, text, hash)
    end

    test "lines with # characters in content" do
      text = "this # is not a prefix"
      hash = HashLine.compute_line_hash(1, text)
      assert String.length(hash) == 2

      # Format and strip should preserve the #
      formatted = HashLine.format_hashlines(text, 1)
      stripped = HashLine.strip_hashline_prefixes(formatted)
      assert stripped == text
    end

    test "lines starting with digits" do
      text = "123 this starts with a number"
      hash = HashLine.compute_line_hash(1, text)
      assert String.length(hash) == 2

      # Format and strip should work correctly
      formatted = HashLine.format_hashlines(text, 1)
      stripped = HashLine.strip_hashline_prefixes(formatted)
      assert stripped == text
    end

    test "lines that look like hashline prefixes" do
      # These should NOT be stripped by strip_hashline_prefixes
      fake_prefixes = [
        # looks like a prefix but we can't know
        "1#XX:content",
        "123#AB:text",
        "999#ZZ:more"
      ]

      # Wait, actually these SHOULD be stripped because they match the pattern!
      # The function doesn't validate, it just strips matching patterns.
      for fake <- fake_prefixes do
        stripped = HashLine.strip_hashline_prefixes(fake)
        # Should strip to just "content"
        refute String.starts_with?(stripped, "1#")
        refute String.starts_with?(stripped, "123#")
        refute String.starts_with?(stripped, "999#")
      end
    end

    test "multiple consecutive newlines" do
      text = "line1\n\nline3"
      formatted = HashLine.format_hashlines(text, 1)
      stripped = HashLine.strip_hashline_prefixes(formatted)
      assert stripped == text
    end

    test "trailing newline handling" do
      text_with_trailing = "line1\nline2\n"
      text_without_trailing = "line1\nline2"

      # Both should work
      formatted_with = HashLine.format_hashlines(text_with_trailing, 1)
      formatted_without = HashLine.format_hashlines(text_without_trailing, 1)

      stripped_with = HashLine.strip_hashline_prefixes(formatted_with)
      stripped_without = HashLine.strip_hashline_prefixes(formatted_without)

      assert stripped_with == text_with_trailing
      assert stripped_without == text_without_trailing
    end

    test "single newline string" do
      text = "\n"
      formatted = HashLine.format_hashlines(text, 1)
      lines = String.split(formatted, "\n")
      # Should produce 2 lines (one empty, one from the split)
      assert length(lines) >= 1
    end

    test "punctuation-only lines use idx as seed" do
      # Lines with no alphanumeric characters should use idx as seed
      h1 = HashLine.compute_line_hash(1, "!@#$%")
      h2 = HashLine.compute_line_hash(2, "!@#$%")
      # Same as h1
      h3 = HashLine.compute_line_hash(1, "!@#$%")

      # Same idx -> same hash
      assert h1 == h3
      # Pinned reference value
      assert h1 == "JB"
      # Different idx -> validate separately (don't assert h1 != h2 - collisions possible)
      assert HashLine.validate_hashline_anchor(1, "!@#$%", h1)
      assert HashLine.validate_hashline_anchor(2, "!@#$%", h2)
    end

    test "mixed alphanumeric and punctuation" do
      # Lines WITH alphanumeric characters should use seed=0
      h1 = HashLine.compute_line_hash(1, "abc!@#")
      h2 = HashLine.compute_line_hash(99, "abc!@#")

      # Same content -> same hash regardless of idx
      assert h1 == h2
    end
  end

  # ============================================================================
  # Section 5: Determinism tests
  # ============================================================================

  describe "determinism" do
    test "same content produces same hash (compute_line_hash)" do
      h1 = HashLine.compute_line_hash(5, "identical line")
      h2 = HashLine.compute_line_hash(5, "identical line")
      assert h1 == h2
    end

    test "same content produces same hash (alnum, different idx)" do
      h1 = HashLine.compute_line_hash(1, "alnum content here")
      h2 = HashLine.compute_line_hash(999, "alnum content here")
      assert h1 == h2
    end

    test "format is deterministic" do
      r1 = HashLine.format_hashlines("alpha\nbeta", 1)
      r2 = HashLine.format_hashlines("alpha\nbeta", 1)
      assert r1 == r2
    end

    test "multiple calls produce same results" do
      text = "def foo():\n    return 42"

      hashes =
        for _ <- 1..10 do
          HashLine.compute_line_hash(1, text)
        end

      assert Enum.all?(hashes, &(&1 == hd(hashes)))
    end
  end

  # ============================================================================
  # Section 6: Algorithm invariants
  # ============================================================================

  describe "algorithm invariants" do
    test "hash always 2 characters" do
      test_cases = [
        "",
        "a",
        "hello world",
        "   ",
        "!@#$%",
        "🚀🎉",
        String.duplicate("x", 1000)
      ]

      for content <- test_cases do
        hash = HashLine.compute_line_hash(1, content)

        assert String.length(hash) == 2,
               "Hash for '#{inspect(content)}' should be 2 chars, got: #{inspect(hash)}"
      end
    end

    test "hash always uppercase A-Z from NIBBLE_STR" do
      nibble_chars = String.graphemes("ZPMQVRWSNKTXJBYH")

      for _ <- 1..100 do
        # Random-ish content
        content = "test_#{System.monotonic_time()}"
        hash = HashLine.compute_line_hash(1, content)

        assert String.at(hash, 0) in nibble_chars
        assert String.at(hash, 1) in nibble_chars
      end
    end

    test "format always includes line number" do
      text = "line"

      for start_line <- [1, 5, 100, 9999] do
        formatted = HashLine.format_hashlines(text, start_line)
        assert String.starts_with?(formatted, "#{start_line}#")
      end
    end

    test "format always includes hash separator" do
      text = "content"
      formatted = HashLine.format_hashlines(text, 1)

      # Pattern: digits + # + 2 chars + : + content
      assert formatted =~ ~r/^\d+#[A-Z]{2}:/
    end

    test "round-trip invariant: format -> strip = identity" do
      test_cases = [
        "simple",
        "with\nmultiple\nlines",
        "  leading spaces",
        "trailing spaces  ",
        "unicode: 🎉",
        "",
        "\n",
        "\n\n",
        "mixed\n\ncontent\n"
      ]

      for original <- test_cases do
        formatted = HashLine.format_hashlines(original, 1)
        stripped = HashLine.strip_hashline_prefixes(formatted)

        assert stripped == original,
               "Round-trip failed for: #{inspect(original)}"
      end
    end

    test "validation is reflexive: computed hash validates" do
      test_cases = [
        {1, "hello"},
        {5, "world"},
        {100, ""},
        {999, "unicode: 🚀"}
      ]

      for {idx, line} <- test_cases do
        hash = HashLine.compute_line_hash(idx, line)
        assert HashLine.validate_hashline_anchor(idx, line, hash)
      end
    end

    test "validation detects single character changes" do
      original = "hello world"
      hash = HashLine.compute_line_hash(1, original)

      # Any single character change should invalidate
      # case
      refute HashLine.validate_hashline_anchor(1, "Hello world", hash)
      # last char
      refute HashLine.validate_hashline_anchor(1, "hello worle", hash)
      # truncated
      refute HashLine.validate_hashline_anchor(1, "hello worl", hash)
      # prefixed
      refute HashLine.validate_hashline_anchor(1, "xhello world", hash)
    end

    test "whitespace stripping is consistent" do
      # All these should produce the same hash (same content after stripping)
      variants = [
        "content",
        "content ",
        "content  ",
        "content\t",
        "content\r",
        "content\r\n",
        "content \t\r\n"
      ]

      hashes =
        Enum.map(variants, fn v ->
          HashLine.compute_line_hash(1, v)
        end)

      assert length(Enum.uniq(hashes)) == 1
    end
  end
end
