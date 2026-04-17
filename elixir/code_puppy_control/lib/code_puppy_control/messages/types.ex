defmodule CodePuppyControl.Messages.Types do
  @moduledoc "Shared type definitions for message processing."

  @type message_part :: %{
          part_kind: String.t(),
          content: String.t() | nil,
          content_json: String.t() | nil,
          tool_call_id: String.t() | nil,
          tool_name: String.t() | nil,
          args: String.t() | nil
        }

  @type message :: %{
          kind: String.t(),
          role: String.t() | nil,
          instructions: String.t() | nil,
          parts: [message_part()]
        }
end
