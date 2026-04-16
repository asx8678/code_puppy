defmodule CodePuppyControl.Text.EOLTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.Text.EOL

  @bom <<0xEF, 0xBB, 0xBF>>

  describe "looks_textish/1" do
    test "empty string is text" do
      assert EOL.looks_textish("")
    end

    test "pure ascii text is text" do
      assert EOL.looks_textish("Hello, world!\nSecond line.\n")
    end

    test "source code is text" do
      content = "def foo():\n    return :ok\n"
      assert EOL.looks_textish(content)
    end

    test "tabs and CRLF still count as text" do
      assert EOL.looks_textish("col1\tcol2\r\ncol3\tcol4\r\n")
    end

    test "NUL byte marks content as binary" do
      refute EOL.looks_textish("hello" <> <<0>> <> "world")
    end

    test "high control-character ratio is binary" do
      refute EOL.looks_textish("\x01\x02\x03\x04\x05\x06\x07\x08ab")
    end

    test "exactly 90 percent printable passes" do
      assert EOL.looks_textish("abcdefghi\x01")
    end

    test "just below 90 percent printable fails" do
      content = String.duplicate("a", 89) <> String.duplicate("\x01", 11)
      refute EOL.looks_textish(content)
    end

    test "unicode text counts as text" do
      assert EOL.looks_textish("日本語テキスト 🐶\n")
    end

    test "invalid utf8 is treated as binary" do
      refute EOL.looks_textish(<<0xFF, 0xFE, 0xFD>>)
    end
  end

  describe "normalize_eol/1" do
    test "empty string stays empty" do
      assert EOL.normalize_eol("") == ""
    end

    test "already-normalized LF content is unchanged" do
      content = "line1\nline2\nline3"
      assert EOL.normalize_eol(content) == content
    end

    test "CRLF is converted to LF" do
      assert EOL.normalize_eol("line1\r\nline2\r\nline3") == "line1\nline2\nline3"
    end

    test "orphan CR becomes LF" do
      assert EOL.normalize_eol("line1\rline2\rline3") == "line1\nline2\nline3"
    end

    test "binary-looking content is left alone" do
      binary_like = "PK" <> <<0>> <> "\x03\x04\r\n" <> <<0, 0, 0>>
      assert EOL.normalize_eol(binary_like) == binary_like
    end

    test "invalid utf8 content is left alone" do
      content = <<0xFF, 0xFE, 0x0D, 0x0A>>
      assert EOL.normalize_eol(content) == content
    end
  end

  describe "strip_bom/1 and restore_bom/2" do
    test "strip_bom removes a leading UTF-8 BOM" do
      assert EOL.strip_bom(@bom <> "hello world") == {"hello world", @bom}
    end

    test "strip_bom leaves non-BOM content alone" do
      assert EOL.strip_bom("hello world") == {"hello world", ""}
    end

    test "strip_bom only removes a BOM at the beginning" do
      content = "hello" <> @bom <> "world"
      assert EOL.strip_bom(content) == {content, ""}
    end

    test "restore_bom prepends the captured marker" do
      assert EOL.restore_bom("hello", @bom) == @bom <> "hello"
    end

    test "roundtrip preserves BOM after modification" do
      original = @bom <> "original content"
      {stripped, bom} = EOL.strip_bom(original)
      restored = EOL.restore_bom(String.replace(stripped, "original", "modified"), bom)
      assert restored == @bom <> "modified content"
    end
  end
end
