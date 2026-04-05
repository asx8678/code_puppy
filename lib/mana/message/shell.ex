defmodule Mana.Message.Shell do
  @moduledoc """
  Shell command execution message type.

  Represents shell command execution with output and exit code.

  ## Fields

  Common fields (from `Mana.Message`):
  - `:id` - String UUID
  - `:timestamp` - DateTime
  - `:category` - Always `:shell`
  - `:session_id` - Optional session identifier

  Type-specific fields (use string keys for JSON-serializable maps):
  - `:command` - String command that was executed
  - `:output` - String output from the command
  - `:exit_code` - Integer exit code (0 for success)

  When working with plain maps for JSON serialization, use string keys:
  `%{"command" => "ls", "output" => "files", "exit_code" => 0}`

  ## Examples

      %Mana.Message.Shell{
        id: "550e8400-e29b-41d4-a716-446655440000",
        timestamp: ~U[2024-01-15 10:30:00Z],
        category: :shell,
        session_id: "session_123",
        command: "ls -la",
        output: "total 0\\ndrwxr-xr-x  3 user group 60 Jan 15 10:30 .",
        exit_code: 0
      }
  """

  @type t :: %__MODULE__{
          id: String.t(),
          timestamp: DateTime.t(),
          category: :shell,
          session_id: String.t() | nil,
          command: String.t(),
          output: String.t(),
          exit_code: integer()
        }

  defstruct [
    :id,
    :timestamp,
    :category,
    :session_id,
    :command,
    :output,
    :exit_code
  ]
end
