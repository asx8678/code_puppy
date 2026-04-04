defmodule Mana.Message.Agent do
  @moduledoc """
  Agent lifecycle message type.

  Represents agent invocation, results, and errors.

  ## Fields

  Common fields (from `Mana.Message`):
  - `:id` - String UUID
  - `:timestamp` - DateTime
  - `:category` - Always `:agent`
  - `:session_id` - Optional session identifier

  Type-specific fields:
  - `:agent_name` - String agent name
  - `:action` - Atom: `:invoke`, `:result`, or `:error`
  - `:payload` - Map with action-specific data

  ## Examples

      # Invocation
      %Mana.Message.Agent{
        id: "550e8400-e29b-41d4-a716-446655440000",
        timestamp: ~U[2024-01-15 10:30:00Z],
        category: :agent,
        session_id: "session_123",
        agent_name: "code_puppy",
        action: :invoke,
        payload: %{task: "Implement feature"}
      }

      # Result
      %Mana.Message.Agent{
        id: "550e8400-e29b-41d4-a716-446655440001",
        timestamp: ~U[2024-01-15 10:30:05Z],
        category: :agent,
        session_id: "session_123",
        agent_name: "code_puppy",
        action: :result,
        payload: %{result: "Feature implemented"}
      }
  """

  @typedoc "Agent action atoms"
  @type action :: :invoke | :result | :error

  @type t :: %__MODULE__{
          id: String.t(),
          timestamp: DateTime.t(),
          category: :agent,
          session_id: String.t() | nil,
          agent_name: String.t(),
          action: action(),
          payload: map()
        }

  defstruct [
    :id,
    :timestamp,
    :category,
    :session_id,
    :agent_name,
    :action,
    :payload
  ]
end
