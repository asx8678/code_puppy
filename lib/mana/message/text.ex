defmodule Mana.Message.Text do
  @moduledoc """
  Text message type for chat/content messages.

  Used for communication between users, assistants, and the system.

  ## Fields

  Common fields (from `Mana.Message`):
  - `:id` - String UUID
  - `:timestamp` - DateTime
  - `:category` - Always `:text`
  - `:session_id` - Optional session identifier

  Type-specific fields:
  - `:content` - String content
  - `:role` - Atom: `:user`, `:assistant`, or `:system`

  ## Examples

      %Mana.Message.Text{
        id: "550e8400-e29b-41d4-a716-446655440000",
        timestamp: ~U[2024-01-15 10:30:00Z],
        category: :text,
        session_id: "session_123",
        content: "Hello, world!",
        role: :user
      }
  """

  @typedoc "Text role atoms"
  @type role :: :user | :assistant | :system

  @type t :: %__MODULE__{
          id: String.t(),
          timestamp: DateTime.t(),
          category: :text,
          session_id: String.t() | nil,
          content: String.t(),
          role: role()
        }

  defstruct [
    :id,
    :timestamp,
    :category,
    :session_id,
    :content,
    :role
  ]
end
