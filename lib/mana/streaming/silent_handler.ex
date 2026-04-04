defmodule Mana.Streaming.SilentHandler do
  @moduledoc """
  Metrics-only handler for sub-agent runs.

  This handler tracks streaming events and token counts without emitting
  to MessageBus. It's designed for sub-agent runs where output should not
  be displayed to the user, but metrics still need to be collected.

  ## Features

  - Tracks active parts using PartTracker
  - Accumulates events in state for later analysis
  - Tracks token counts without emitting to MessageBus
  - Suitable for background/sub-agent processing

  ## State

  - `:session_id` - Optional session identifier for correlation
  - `:events` - List of accumulated events (reversed for efficient prepend)
  - `:part_tracker` - PartTracker struct tracking active parts and tokens

  ## Usage

      state = %Mana.Streaming.SilentHandler{
        session_id: "session_123",
        events: [],
        part_tracker: Mana.Streaming.PartTracker.new()
      }

      {:ok, state} = Mana.Streaming.SilentHandler.handle_part_start(
        state, "part_1", :text, %{}
      )

      {input, output} = Mana.Streaming.SilentHandler.get_metrics(state)
  """

  alias Mana.Streaming.EventHandler
  alias Mana.Streaming.PartTracker

  @behaviour EventHandler

  defstruct [
    :session_id,
    :events,
    :part_tracker
  ]

  @type t :: %__MODULE__{
          session_id: String.t() | nil,
          events: list(),
          part_tracker: PartTracker.t()
        }

  @doc """
  Creates a new SilentHandler with the given options.

  ## Options

  - `:session_id` - Optional session identifier

  ## Example

      handler = Mana.Streaming.SilentHandler.new(session_id: "session_123")
  """
  @spec new(keyword()) :: t()
  def new(opts \\ []) do
    %__MODULE__{
      session_id: Keyword.get(opts, :session_id),
      events: [],
      part_tracker: PartTracker.new()
    }
  end

  @doc """
  Returns the accumulated events from the handler state.

  Events are stored in reverse order (most recent first) for efficient
  prepending. This function returns them in chronological order.

  ## Example

      events = Mana.Streaming.SilentHandler.events(state)
  """
  @spec events(t()) :: list()
  def events(state), do: Enum.reverse(state.events)

  @doc """
  Returns the part tracker from the handler state.

  ## Example

      tracker = Mana.Streaming.SilentHandler.part_tracker(state)
  """
  @spec part_tracker(t()) :: PartTracker.t()
  def part_tracker(state), do: state.part_tracker

  @impl true
  def handle_part_start(state, part_id, type, meta) do
    tracker = PartTracker.start_part(state.part_tracker, part_id, type)

    {:ok,
     %__MODULE__{
       state
       | part_tracker: tracker,
         events: [{:part_start, part_id, type, meta} | state.events]
     }}
  end

  @impl true
  def handle_part_delta(state, part_id, _content) do
    # Track token count without emitting to MessageBus
    # Each delta counts as 1 output token (simplified counting)
    tracker = PartTracker.update_tokens(state.part_tracker, part_id, 0, 1)

    {:ok, %{state | part_tracker: tracker}}
  end

  @impl true
  def handle_part_end(state, part_id, meta) do
    tracker = PartTracker.end_part(state.part_tracker, part_id)

    {:ok,
     %__MODULE__{
       state
       | part_tracker: tracker,
         events: [{:part_end, part_id, meta} | state.events]
     }}
  end

  @doc """
  Returns the total token counts from the part tracker.

  ## Example

      {input, output} = Mana.Streaming.SilentHandler.get_metrics(state)
  """
  @spec get_metrics(t()) :: {non_neg_integer(), non_neg_integer()}
  def get_metrics(state) do
    PartTracker.total_tokens(state.part_tracker)
  end

  @doc """
  Returns the number of accumulated events.

  ## Example

      count = Mana.Streaming.SilentHandler.event_count(state)
  """
  @spec event_count(t()) :: non_neg_integer()
  def event_count(state), do: length(state.events)

  @doc """
  Checks if any active part has the given type.

  ## Example

      is_thinking = Mana.Streaming.SilentHandler.active_type?(state, :thinking)
  """
  @spec active_type?(t(), atom()) :: boolean()
  def active_type?(state, type) do
    PartTracker.active_type?(state.part_tracker, type)
  end
end
