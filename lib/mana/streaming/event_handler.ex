defmodule Mana.Streaming.EventHandler do
  @moduledoc """
  Behaviour for stream event handling.

  Defines the callback interface for handling streaming events from
  LLM responses. Implementations handle part start, delta (content),
  and end events during streaming.

  ## Callbacks

  - `handle_part_start/4` - Called when a new streaming part begins
  - `handle_part_delta/3` - Called when content is received for a part
  - `handle_part_end/3` - Called when a streaming part completes

  ## Usage

  Implement the behaviour in your handler module:

      defmodule MyHandler do
        @behaviour Mana.Streaming.EventHandler

        @impl true
        def handle_part_start(state, part_id, type, metadata) do
          # Handle part start
          {:ok, new_state}
        end

        @impl true
        def handle_part_delta(state, part_id, content) do
          # Handle content delta
          {:ok, new_state}
        end

        @impl true
        def handle_part_end(state, part_id, metadata) do
          # Handle part end
          {:ok, new_state}
        end
      end

  Use the shared driver function to process events:

      Mana.Streaming.EventHandler.process_events(MyHandler, state, events)
  """

  alias Mana.Callbacks

  @doc """
  Called when a new streaming part begins.

  ## Parameters

  - `handler_state` - The current handler state
  - `part_id` - Unique identifier for the part
  - `type` - Atom indicating the part type (e.g., `:text`, `:thinking`, `:tool`)
  - `metadata` - Map with additional metadata about the part

  ## Returns

  `{:ok, new_state}` on success.
  """
  @callback handle_part_start(handler_state :: term(), part_id :: String.t(), type :: atom(), metadata :: map()) ::
              {:ok, term()}

  @doc """
  Called when content is received for a streaming part.

  ## Parameters

  - `handler_state` - The current handler state
  - `part_id` - Unique identifier for the part
  - `content` - String content chunk received

  ## Returns

  `{:ok, new_state}` on success.
  """
  @callback handle_part_delta(handler_state :: term(), part_id :: String.t(), content :: String.t()) ::
              {:ok, term()}

  @doc """
  Called when a streaming part completes.

  ## Parameters

  - `handler_state` - The current handler state
  - `part_id` - Unique identifier for the part
  - `metadata` - Map with additional metadata about the completed part

  ## Returns

  `{:ok, new_state}` on success.
  """
  @callback handle_part_end(handler_state :: term(), part_id :: String.t(), metadata :: map()) ::
              {:ok, term()}

  @doc """
  Shared driver function to process a list of events.

  Iterates through events and calls the appropriate handler callbacks.
  Events should be tuples of the form:

  - `{:part_start, part_id, type, metadata}`
  - `{:part_delta, part_id, content}`
  - `{:part_end, part_id, metadata}`

  ## Parameters

  - `handler_mod` - Module implementing the EventHandler behaviour
  - `handler_state` - Initial handler state
  - `events` - List of event tuples to process

  ## Returns

  `{:ok, final_state}` after processing all events.

  ## Example

      events = [
        {:part_start, "part_1", :text, %{}},
        {:part_delta, "part_1", "Hello"},
        {:part_end, "part_1", %{}}
      ]
      {:ok, final_state} = Mana.Streaming.EventHandler.process_events(MyHandler, state, events)
  """
  @spec process_events(module(), term(), list()) :: {:ok, term()}
  def process_events(handler_mod, handler_state, events) do
    Enum.reduce(events, {:ok, handler_state}, fn
      {:part_start, part_id, type, meta}, {:ok, state} ->
        handler_mod.handle_part_start(state, part_id, type, meta)

      {:part_delta, part_id, content}, {:ok, state} ->
        handler_mod.handle_part_delta(state, part_id, content)

      {:part_end, part_id, meta}, {:ok, state} ->
        handler_mod.handle_part_end(state, part_id, meta)

      _, acc ->
        acc
    end)
  end

  @doc """
  Fires the `:stream_event` callback for TTSR and other listeners.

  Dispatches to all registered callbacks with the event type, data, and session ID.
  This enables plugins like TTSR (Test-Time Safety Rules) to monitor streaming events.

  ## Parameters

  - `event_type` - Atom indicating the event type (e.g., `:part_start`, `:part_delta`, `:part_end`)
  - `event_data` - Map containing event-specific data
  - `session_id` - Optional session identifier (can be nil)

  ## Returns

  `{:ok, results}` from the Callbacks.dispatch/2 call.

  ## Example

      Mana.Streaming.EventHandler.fire_stream_callback(
        :part_start,
        %{part_id: "part_1", type: :text},
        "session_123"
      )
  """
  @spec fire_stream_callback(atom(), map(), String.t() | nil) :: {:ok, list()} | {:error, term()}
  def fire_stream_callback(event_type, event_data, session_id) do
    Callbacks.dispatch(:stream_event, [event_type, event_data, session_id])
  end
end
