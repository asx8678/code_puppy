defmodule Mana.Message.UserInteraction do
  @moduledoc """
  User interaction request message type.

  Represents requests for user input such as text input,
  confirmations, or selections.

  ## Fields

  Common fields (from `Mana.Message`):
  - `:id` - String UUID
  - `:timestamp` - DateTime
  - `:category` - Always `:user_interaction`
  - `:session_id` - Optional session identifier

  Type-specific fields:
  - `:prompt` - String prompt displayed to user
  - `:response` - String user response (nil until provided)
  - `:interaction_type` - Atom: `:input`, `:confirmation`, or `:selection`
  - `:payload` - Map for additional data (e.g., `choices` for selection)

  ## Examples

      # Input request
      %Mana.Message.UserInteraction{
        id: "550e8400-e29b-41d4-a716-446655440000",
        timestamp: ~U[2024-01-15 10:30:00Z],
        category: :user_interaction,
        session_id: "session_123",
        prompt: "Enter your name:",
        response: nil,
        interaction_type: :input
      }

      # Confirmation request
      %Mana.Message.UserInteraction{
        id: "550e8400-e29b-41d4-a716-446655440001",
        timestamp: ~U[2024-01-15 10:30:01Z],
        category: :user_interaction,
        session_id: "session_123",
        prompt: "Delete this file?",
        response: nil,
        interaction_type: :confirmation
      }
  """

  @typedoc "User interaction type atoms"
  @type interaction_type :: :input | :confirmation | :selection

  @type t :: %__MODULE__{
          id: String.t(),
          timestamp: DateTime.t(),
          category: :user_interaction,
          session_id: String.t() | nil,
          prompt: String.t(),
          response: String.t() | nil,
          interaction_type: interaction_type(),
          payload: map() | nil
        }

  defstruct [
    :id,
    :timestamp,
    :category,
    :session_id,
    :prompt,
    :response,
    :interaction_type,
    :payload
  ]
end
