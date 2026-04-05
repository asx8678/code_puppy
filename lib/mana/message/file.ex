defmodule Mana.Message.File do
  @moduledoc """
  File operation message type.

  Represents file read, write, edit, or delete operations.

  ## Fields

  Common fields (from `Mana.Message`):
  - `:id` - String UUID
  - `:timestamp` - DateTime
  - `:category` - Always `:file`
  - `:session_id` - Optional session identifier

  Type-specific fields:
  - `:path` - String file path
  - `:content` - String content (optional for delete operations)
  - `:operation` - Atom: `:read`, `:write`, `:edit`, or `:delete`

  ## Examples

      %Mana.Message.File{
        id: "550e8400-e29b-41d4-a716-446655440000",
        timestamp: ~U[2024-01-15 10:30:00Z],
        category: :file,
        session_id: "session_123",
        path: "/tmp/test.txt",
        content: "Hello, world!",
        operation: :write
      }
  """

  @typedoc "File operation atoms"
  @type operation :: :read | :write | :edit | :delete

  @type t :: %__MODULE__{
          id: String.t(),
          timestamp: DateTime.t(),
          category: :file,
          session_id: String.t() | nil,
          path: String.t(),
          content: String.t() | nil,
          operation: operation()
        }

  defstruct [
    :id,
    :timestamp,
    :category,
    :session_id,
    :path,
    :content,
    :operation
  ]
end
