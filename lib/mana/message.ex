defmodule Mana.Message do
  @moduledoc """
  Base module for Mana message types.

  Defines common fields shared across all message types and provides
  a factory function for creating messages.

  ## Common Fields

  All message types include:
  - `:id` - String UUID (unique identifier)
  - `:timestamp` - DateTime when the message was created
  - `:category` - Atom indicating message type (`:text`, `:file`, `:shell`,
    `:agent`, `:user_interaction`, `:control`)
  - `:session_id` - Optional string for session correlation

  ## Message Types

  - `Mana.Message.Text` - Text content with role
  - `Mana.Message.File` - File operations
  - `Mana.Message.Shell` - Shell command execution
  - `Mana.Message.Agent` - Agent lifecycle events
  - `Mana.Message.UserInteraction` - User input requests
  - `Mana.Message.Control` - System control commands
  """

  @typedoc "Message category atoms"
  @type category :: :text | :file | :shell | :agent | :user_interaction | :control

  @typedoc "Common fields present in all message types"
  @type t :: %{
          id: String.t(),
          timestamp: DateTime.t(),
          category: category(),
          session_id: String.t() | nil
        }

  @doc """
  Creates a new message of the specified category with the given attributes.

  Auto-generates `:id` (UUID v4) and `:timestamp` (UTC) if not provided.

  ## Examples

      iex> Mana.Message.new(:text, %{content: "Hello", role: :user})
      %Mana.Message.Text{id: "...", timestamp: ~U[...], category: :text, content: "Hello", role: :user}

      iex> Mana.Message.new(:shell, %{command: "ls -la", output: "...", exit_code: 0})
      %Mana.Message.Shell{...}
  """
  @spec new(category(), map()) :: struct()
  def new(category, attrs) when is_atom(category) and is_map(attrs) do
    # Generate common fields
    common = %{
      id: attrs[:id] || generate_uuid(),
      timestamp: attrs[:timestamp] || DateTime.utc_now(),
      category: category,
      session_id: attrs[:session_id]
    }

    # Merge with type-specific fields and create the appropriate struct
    create_struct(category, common, attrs)
  end

  def new(category, _attrs) do
    raise ArgumentError, "Unknown message category: #{inspect(category)}"
  end

  defp create_struct(:text, common, attrs) do
    struct(Mana.Message.Text, Map.merge(common, attrs))
  end

  defp create_struct(:file, common, attrs) do
    struct(Mana.Message.File, Map.merge(common, attrs))
  end

  defp create_struct(:shell, common, attrs) do
    struct(Mana.Message.Shell, Map.merge(common, attrs))
  end

  defp create_struct(:agent, common, attrs) do
    struct(Mana.Message.Agent, Map.merge(common, attrs))
  end

  defp create_struct(:user_interaction, common, attrs) do
    struct(Mana.Message.UserInteraction, Map.merge(common, attrs))
  end

  defp create_struct(:control, common, attrs) do
    struct(Mana.Message.Control, Map.merge(common, attrs))
  end

  defp create_struct(category, _common, _attrs) do
    raise ArgumentError, "Unknown message category: #{inspect(category)}"
  end

  # ---------------------------------------------------------------------------
  # Key normalization
  # ---------------------------------------------------------------------------

  @doc """
  Normalizes message map keys from strings to atoms.

  Called at ingestion boundaries (JSON decode, session load, provider response
  parsing) to ensure consistent atom-keyed maps throughout the internal pipeline.

  Uses `String.to_existing_atom/1` for security - only converts strings to atoms
  that already exist in the BEAM VM, preventing atom table exhaustion attacks.

  Handles nested structures: `tool_calls` lists and `function` maps are
  recursively normalized.

  ## Examples

      iex> Mana.Message.normalize_keys(%{"role" => "user", "content" => "hi"})
      %{role: "user", content: "hi"}

      iex> Mana.Message.normalize_keys(%{role: "user", "content" => "hi"})
      %{role: "user", content: "hi"}
  """
  @spec normalize_keys(map()) :: map()
  def normalize_keys(%{} = msg) do
    msg
    |> Map.new(fn
      {k, v} when is_binary(k) -> {safe_to_atom(k), v}

      pair ->
        pair
    end)
    |> maybe_normalize_nested()
  end

  @spec normalize_keys(list()) :: list()
  def normalize_keys(list) when is_list(list), do: Enum.map(list, &normalize_keys/1)

  @spec normalize_keys(any()) :: any()
  def normalize_keys(other), do: other

  # Known message keys that are safe to convert to atoms.
  # Unknown keys stay as strings to prevent atom table exhaustion.
  @known_keys ~w(role content tool_calls function name arguments tool_call_id
                 type id refusal model finish_reason index delta message
                 logprobs usage choices error session_id timestamp category
                 created object system_fingerprint)a

  defp safe_to_atom(key) when is_binary(key) do
    if key in Enum.map(@known_keys, &Atom.to_string/1),
      do: String.to_existing_atom(key),
      else: key
  rescue
    ArgumentError -> key
  end

  defp maybe_normalize_nested(%{tool_calls: calls} = msg) when is_list(calls) do
    %{msg | tool_calls: Enum.map(calls, &normalize_keys/1)}
  end

  defp maybe_normalize_nested(%{function: %{} = func} = msg) do
    %{msg | function: normalize_keys(func)}
  end

  defp maybe_normalize_nested(msg), do: msg

  @doc """
  Normalizes a list of messages, applying `normalize_keys/1` to each.

  Convenience function for use at ingestion boundaries that receive a list
  of messages (e.g., session loading from disk).

  ## Examples

      iex> messages = [%{"role" => "user"}, %{"role" => "assistant"}]
      iex> Mana.Message.normalize_list(messages)
      [%{role: "user"}, %{role: "assistant"}]
  """
  @spec normalize_list([map()]) :: [map()]
  def normalize_list(messages) when is_list(messages) do
    Enum.map(messages, &normalize_keys/1)
  end

  @doc """
  Generates a UUID v4 string.

  UUID v4 format: xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx
  where 4 is the version and y is 8, 9, a, or b
  """
  @spec generate_uuid() :: String.t()
  def generate_uuid do
    # Generate 16 random bytes
    <<a1::4, a2::4, a3::4, a4::4, a5::4, a6::4, a7::4, a8::4, b1::4, b2::4, b3::4, b4::4, _c1::4, c2::4, c3::4, c4::4,
      _d1::4, d2::4, d3::4, d4::4, e1::4, e2::4, e3::4, e4::4, e5::4, e6::4, e7::4, e8::4, e9::4, e10::4, e11::4,
      e12::4>> = :crypto.strong_rand_bytes(16)

    # Set version (4) in c1
    c1 = 4

    # Set variant (8/b/a/9) in d1
    d1 = 8 + (:rand.uniform(4) - 1)

    hex =
      [
        a1,
        a2,
        a3,
        a4,
        a5,
        a6,
        a7,
        a8,
        b1,
        b2,
        b3,
        b4,
        c1,
        c2,
        c3,
        c4,
        d1,
        d2,
        d3,
        d4,
        e1,
        e2,
        e3,
        e4,
        e5,
        e6,
        e7,
        e8,
        e9,
        e10,
        e11,
        e12
      ]
      |> Enum.map_join(&Integer.to_string(&1, 16))
      |> String.downcase()

    <<p1::binary-8, p2::binary-4, p3::binary-4, p4::binary-4, p5::binary-12>> = hex

    "#{p1}-#{p2}-#{p3}-#{p4}-#{p5}"
  end
end
