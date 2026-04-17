defmodule CodePuppyControl.Messages.Hasher do
  @moduledoc "Fast message hashing. Port of code_puppy_core/src/message_hashing.rs."

  alias CodePuppyControl.Messages.Types

  @doc """
  Compute a stable hash for a message.
  Mirrors `BaseAgent.hash_message()` — builds a canonical string from
  header bits + part strings, then hashes it.
  Uses :erlang.phash2 for fast hashing.
  """
  @spec hash_message(Types.message()) :: integer()
  def hash_message(msg) do
    # Build header bits from role and instructions
    header_bits =
      []
      |> maybe_add_header("role", msg[:role])
      |> maybe_add_header("instructions", msg[:instructions])

    # Build part strings
    part_strings = Enum.map(msg[:parts] || [], &stringify_part_for_hash/1)

    # Combine all parts into canonical string
    canonical = Enum.join(header_bits ++ part_strings, "||")

    # Use :erlang.phash2 for fast hashing (converts to signed int like Rust FxHasher)
    :erlang.phash2(canonical)
  end

  @spec maybe_add_header([String.t()], String.t(), String.t() | nil) :: [String.t()]
  defp maybe_add_header(bits, _key, nil), do: bits
  defp maybe_add_header(bits, _key, ""), do: bits

  defp maybe_add_header(bits, key, value) do
    bits ++ ["#{key}=#{value}"]
  end

  @doc """
  Build the canonical string for a part (for hashing).
  Mirrors `BaseAgent._stringify_part()` in Python.
  """
  @spec stringify_part_for_hash(Types.message_part()) :: String.t()
  def stringify_part_for_hash(part) do
    attributes =
      [part[:part_kind]]
      |> maybe_add_attr("tool_call_id", part[:tool_call_id])
      |> maybe_add_attr("tool_name", part[:tool_name])
      |> add_content_attr(part[:content], part[:content_json])

    Enum.join(attributes, "|")
  end

  @spec maybe_add_attr([String.t()], String.t(), String.t() | nil) :: [String.t()]
  defp maybe_add_attr(attrs, _key, nil), do: attrs
  defp maybe_add_attr(attrs, _key, ""), do: attrs

  defp maybe_add_attr(attrs, key, value) do
    attrs ++ ["#{key}=#{value}"]
  end

  @spec add_content_attr([String.t()], String.t() | nil, String.t() | nil) :: [String.t()]
  defp add_content_attr(attrs, nil, nil), do: attrs ++ ["content=None"]
  defp add_content_attr(attrs, "" = _content, nil), do: attrs ++ ["content=None"]

  defp add_content_attr(attrs, content, _json) when is_binary(content),
    do: attrs ++ ["content=#{content}"]

  defp add_content_attr(attrs, nil, json) when is_binary(json), do: attrs ++ ["content=#{json}"]
end
