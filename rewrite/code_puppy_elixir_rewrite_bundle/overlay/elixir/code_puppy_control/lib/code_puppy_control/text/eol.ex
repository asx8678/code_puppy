defmodule CodePuppyControl.Text.EOL do
  @moduledoc """
  End-of-line normalization with binary-file detection.

  Port of `code_puppy/utils/eol.py`.

  Behavior:
  - content with NUL bytes is treated as binary
  - invalid UTF-8 is treated as binary
  - valid UTF-8 content is considered text when at least 90% of characters
    are printable or common whitespace (`\\t`, `\\n`, `\\r`)
  - CRLF is normalized to LF for text content only
  - leading UTF-8 BOM is stripped and can later be restored
  """

  @utf8_bom <<0xEF, 0xBB, 0xBF>>

  @spec looks_textish(binary()) :: boolean()
  def looks_textish(""), do: true

  def looks_textish(content) when is_binary(content) do
    cond do
      :binary.match(content, <<0>>) != :nomatch ->
        false

      not String.valid?(content) ->
        false

      true ->
        chars = String.to_charlist(content)
        total = length(chars)

        printable = Enum.count(chars, &printable_char?/1)

        printable / total >= 0.90
    end
  end

  @spec normalize_eol(binary()) :: binary()
  def normalize_eol(""), do: ""

  def normalize_eol(content) when is_binary(content) do
    if looks_textish(content) do
      content
      |> String.replace("\r\n", "\n")
      |> String.replace("\r", "\n")
    else
      content
    end
  end

  @spec strip_bom(binary()) :: {binary(), binary()}
  def strip_bom(<<0xEF, 0xBB, 0xBF, rest::binary>>), do: {rest, @utf8_bom}
  def strip_bom(content) when is_binary(content), do: {content, ""}

  @spec restore_bom(binary(), binary()) :: binary()
  def restore_bom(content, "") when is_binary(content), do: content
  def restore_bom(content, bom) when is_binary(content) and is_binary(bom), do: bom <> content

  defp printable_char?(ch) when ch >= 0x20, do: true
  defp printable_char?(?\t), do: true
  defp printable_char?(?\n), do: true
  defp printable_char?(?\r), do: true
  defp printable_char?(_), do: false
end
