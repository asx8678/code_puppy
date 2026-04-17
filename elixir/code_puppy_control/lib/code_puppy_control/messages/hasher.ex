defmodule CodePuppyControl.Messages.Hasher do
  @moduledoc """
  Port of `code_puppy_core/src/message_hashing.rs`.

  Fast message hashing using `:erlang.phash2/1` (Erlang's portable hash function).
  This replaces the Rust FxHash implementation for Elixir-native message processing.

  Hash values are consistent within a single session but do NOT need to match
  Rust FxHash values - they are only compared within the same Elixir process.

  ## Algorithm

  1. `stringify_part_for_hash/1` - builds canonical string representation of a part:
     `"part_kind|tool_call_id=X|tool_name=Y|content=Z"` (attributes joined by `|`)

  2. `hash_message/1` - builds header bits (role, instructions), combines with all
     part strings, joins with `||`, then hashes with `:erlang.phash2/1`

  ## Usage

      alias CodePuppyControl.Messages.Hasher

      message = %{
        kind: "request",
        role: "user",
        instructions: nil,
        parts: [%{part_kind: "text", content: "hello", content_json: nil,
                  tool_call_id: nil, tool_name: nil, args: nil}]
      }

      hash = Hasher.hash_message(message)
  """

  alias CodePuppyControl.Messages.Types

  @doc """
  Compute a stable hash for a message.

  Builds a canonical string from header bits (role, instructions) plus all
  part strings, then hashes using `:erlang.phash2/1`.

  ## Parameters

    * `msg` - A message map conforming to `Types.message()`

  ## Returns

    * `integer()` - A positive hash value

  ## Examples

      iex> msg = %{kind: "request", role: "user", instructions: nil, parts: []}
      iex> hash = Hasher.hash_message(msg)
      iex> is_integer(hash) and hash >= 0
      true
  """
  @spec hash_message(Types.message()) :: integer()
  def hash_message(msg) do
    header_bits = build_header_bits(msg)
    part_strings = Enum.map(msg.parts, &stringify_part_for_hash/1)

    canonical =
      header_bits
      |> Enum.concat(part_strings)
      |> Enum.join("||")

    :erlang.phash2(canonical)
  end

  @doc """
  Build the canonical string for a part (for hashing).

  Mirrors the Python `BaseAgent._stringify_part()` method.
  Format: `"part_kind|tool_call_id=X|tool_name=Y|content=Z"`

  ## Parameters

    * `part` - A message part map conforming to `Types.message_part()`

  ## Returns

    * `String.t()` - Canonical string representation
  """
  @spec stringify_part_for_hash(Types.message_part()) :: String.t()
  def stringify_part_for_hash(part) do
    attributes = [part.part_kind]

    attributes =
      if nonempty_string(part.tool_call_id) do
        attributes ++ ["tool_call_id=#{part.tool_call_id}"]
      else
        attributes
      end

    attributes =
      if nonempty_string(part.tool_name) do
        attributes ++ ["tool_name=#{part.tool_name}"]
      else
        attributes
      end

    attributes =
      cond do
        # Rust: if let Some(ref content) = part.content (empty string is Some(""))
        part.content != nil ->
          attributes ++ ["content=#{part.content}"]

        nonempty_string(part.content_json) ->
          attributes ++ ["content=#{part.content_json}"]

        true ->
          attributes ++ ["content=None"]
      end

    Enum.join(attributes, "|")
  end

  # Private functions

  @spec build_header_bits(Types.message()) :: [String.t()]
  defp build_header_bits(msg) do
    bits = []

    bits =
      if nonempty_string(msg.role) do
        ["role=#{msg.role}" | bits]
      else
        bits
      end

    bits =
      if nonempty_string(msg.instructions) do
        ["instructions=#{msg.instructions}" | bits]
      else
        bits
      end

    # Reverse to maintain expected order (role before instructions)
    Enum.reverse(bits)
  end

  @spec nonempty_string(String.t() | nil) :: boolean()
  defp nonempty_string(nil), do: false
  defp nonempty_string(""), do: false
  defp nonempty_string(_), do: true
end
