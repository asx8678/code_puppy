defmodule Mana.Streaming.ConsoleHandler do
  @moduledoc """
  Emits stream chunks to MessageBus for console output.

  Handles thinking banners, tool progress, and text streaming.
  This is the primary handler for interactive agent runs where
  output should be displayed to the user in real-time.

  ## Features

  - Emits stream chunks as Text messages to MessageBus
  - Fires `:stream_event` callbacks for TTSR and other listeners
  - Tracks active parts using PartTracker
  - Handles thinking, tool use, and text content types

  ## State

  - `:session_id` - Optional session identifier for correlation
  - `:part_tracker` - PartTracker struct tracking active parts

  ## Usage

      state = %Mana.Streaming.ConsoleHandler{
        session_id: "session_123",
        part_tracker: Mana.Streaming.PartTracker.new()
      }

      {:ok, new_state} = Mana.Streaming.ConsoleHandler.handle_part_start(
        state, "part_1", :text, %{}
      )
  """

  alias Mana.Message
  alias Mana.MessageBus
  alias Mana.Streaming.EventHandler
  alias Mana.Streaming.PartTracker

  @behaviour EventHandler

  defstruct [
    :session_id,
    :part_tracker
  ]

  @type t :: %__MODULE__{
          session_id: String.t() | nil,
          part_tracker: PartTracker.t()
        }

  @doc """
  Creates a new ConsoleHandler with the given options.

  ## Options

  - `:session_id` - Optional session identifier

  ## Example

      handler = Mana.Streaming.ConsoleHandler.new(session_id: "session_123")
  """
  @spec new(keyword()) :: t()
  def new(opts \\ []) do
    %__MODULE__{
      session_id: Keyword.get(opts, :session_id),
      part_tracker: PartTracker.new()
    }
  end

  @doc """
  Returns the part tracker from the handler state.

  ## Example

      tracker = Mana.Streaming.ConsoleHandler.part_tracker(state)
  """
  @spec part_tracker(t()) :: PartTracker.t()
  def part_tracker(state), do: state.part_tracker

  @impl true
  def handle_part_start(state, part_id, type, meta) do
    tracker = PartTracker.start_part(state.part_tracker, part_id, type)

    # Emit to MessageBus with system role
    MessageBus.emit_text("[#{type}] starting...", role: :system, session_id: state.session_id)

    # Fire callback for TTSR and other listeners
    EventHandler.fire_stream_callback(
      :part_start,
      %{part_id: part_id, type: type, metadata: meta},
      state.session_id
    )

    {:ok, %{state | part_tracker: tracker}}
  end

  @impl true
  def handle_part_delta(state, part_id, content) do
    tracker = PartTracker.update_tokens(state.part_tracker, part_id, 0, 1)

    # Emit content to MessageBus as stream chunk with assistant role
    message =
      Message.new(:text, %{
        content: content,
        role: :assistant,
        session_id: state.session_id
      })

    MessageBus.emit(message)

    # Fire callback for TTSR and other listeners
    EventHandler.fire_stream_callback(
      :part_delta,
      %{part_id: part_id, content: content},
      state.session_id
    )

    {:ok, %{state | part_tracker: tracker}}
  end

  @impl true
  def handle_part_end(state, part_id, meta) do
    tracker = PartTracker.end_part(state.part_tracker, part_id)

    # Fire callback for TTSR and other listeners
    EventHandler.fire_stream_callback(
      :part_end,
      %{part_id: part_id, metadata: meta},
      state.session_id
    )

    {:ok, %{state | part_tracker: tracker}}
  end

  @doc """
  Checks if any active part has the given type.

  ## Example

      is_thinking = Mana.Streaming.ConsoleHandler.active_type?(state, :thinking)
  """
  @spec active_type?(t(), atom()) :: boolean()
  def active_type?(state, type) do
    PartTracker.active_type?(state.part_tracker, type)
  end

  @doc """
  Returns the total token counts from the part tracker.

  ## Example

      {input, output} = Mana.Streaming.ConsoleHandler.total_tokens(state)
  """
  @spec total_tokens(t()) :: {non_neg_integer(), non_neg_integer()}
  def total_tokens(state) do
    PartTracker.total_tokens(state.part_tracker)
  end
end
