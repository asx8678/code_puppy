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
    case category do
      :text ->
        struct(Mana.Message.Text, Map.merge(common, attrs))

      :file ->
        struct(Mana.Message.File, Map.merge(common, attrs))

      :shell ->
        struct(Mana.Message.Shell, Map.merge(common, attrs))

      :agent ->
        struct(Mana.Message.Agent, Map.merge(common, attrs))

      :user_interaction ->
        struct(Mana.Message.UserInteraction, Map.merge(common, attrs))

      :control ->
        struct(Mana.Message.Control, Map.merge(common, attrs))

      _ ->
        raise ArgumentError, "Unknown message category: #{inspect(category)}"
    end
  end

  def new(category, _attrs) do
    raise ArgumentError, "Unknown message category: #{inspect(category)}"
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
      |> Enum.map(&Integer.to_string(&1, 16))
      |> Enum.join()
      |> String.downcase()

    <<p1::binary-8, p2::binary-4, p3::binary-4, p4::binary-4, p5::binary-12>> = hex

    "#{p1}-#{p2}-#{p3}-#{p4}-#{p5}"
  end
end
