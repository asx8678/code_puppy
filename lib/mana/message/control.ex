defmodule Mana.Message.Control do
  @moduledoc """
  System control message type.

  Represents system-level control commands like start, stop, pause, resume.

  ## Fields

  Common fields (from `Mana.Message`):
  - `:id` - String UUID
  - `:timestamp` - DateTime
  - `:category` - Always `:control`
  - `:session_id` - Optional session identifier

  Type-specific fields:
  - `:command` - Atom: `:start`, `:stop`, `:pause`, or `:resume`

  ## Examples

      %Mana.Message.Control{
        id: "550e8400-e29b-41d4-a716-446655440000",
        timestamp: ~U[2024-01-15 10:30:00Z],
        category: :control,
        session_id: "session_123",
        command: :start
      }
  """

  @typedoc "Control command atoms"
  @type command :: :start | :stop | :pause | :resume

  @type t :: %__MODULE__{
          id: String.t(),
          timestamp: DateTime.t(),
          category: :control,
          session_id: String.t() | nil,
          command: command()
        }

  defstruct [
    :id,
    :timestamp,
    :category,
    :session_id,
    :command
  ]
end
