defmodule CodePuppyControl.EventBus do
  @moduledoc """
  Event distribution via Phoenix.PubSub.

  Replaces the Python MessageBus pattern with Elixir-native PubSub.
  Python emits events to Elixir, which broadcasts via PubSub to subscribers.

  ## Topics

  - `"session:<session_id>"` - All events for a session
  - `"run:<run_id>"` - Events for specific run
  - `"global:events"` - System-wide events

  ## Usage

      # Subscribe to events
      EventBus.subscribe_session("session-123")
      EventBus.subscribe_run("run-456")

      # Broadcast events from Python worker
      EventBus.broadcast_text("run-456", "session-123", "Hello from agent")
      EventBus.broadcast_tool_result("run-456", "session-123", "file_read", %{content: "..."})

  ## Event Format

  All events include:
  - `type` - Event type (text, tool_result, status, etc.)
  - `run_id` - Associated run identifier
  - `session_id` - Associated session identifier
  - `timestamp` - UTC DateTime
  - Event-specific fields
  """

  alias Phoenix.PubSub

  @pubsub CodePuppyControl.PubSub

  # ============================================================================
  # Topic Helpers
  # ============================================================================

  @doc """
  Returns the topic name for a session.
  """
  @spec session_topic(String.t()) :: String.t()
  def session_topic(session_id), do: "session:#{session_id}"

  @doc """
  Returns the topic name for a run.
  """
  @spec run_topic(String.t()) :: String.t()
  def run_topic(run_id), do: "run:#{run_id}"

  @doc """
  Returns the global events topic name.
  """
  @spec global_topic() :: String.t()
  def global_topic, do: "global:events"

  # ============================================================================
  # Subscribe
  # ============================================================================

  @doc """
  Subscribe to events for a specific session.

  Returns `:ok` or `{:error, reason}`.
  """
  @spec subscribe_session(String.t()) :: :ok | {:error, term()}
  def subscribe_session(session_id) do
    PubSub.subscribe(@pubsub, session_topic(session_id))
  end

  @doc """
  Subscribe to events for a specific run.

  Returns `:ok` or `{:error, reason}`.
  """
  @spec subscribe_run(String.t()) :: :ok | {:error, term()}
  def subscribe_run(run_id) do
    PubSub.subscribe(@pubsub, run_topic(run_id))
  end

  @doc """
  Subscribe to global events.

  Returns `:ok` or `{:error, reason}`.
  """
  @spec subscribe_global() :: :ok | {:error, term()}
  def subscribe_global do
    PubSub.subscribe(@pubsub, global_topic())
  end

  @doc """
  Unsubscribe from a session topic.
  """
  @spec unsubscribe_session(String.t()) :: :ok | {:error, term()}
  def unsubscribe_session(session_id) do
    PubSub.unsubscribe(@pubsub, session_topic(session_id))
  end

  @doc """
  Unsubscribe from a run topic.
  """
  @spec unsubscribe_run(String.t()) :: :ok | {:error, term()}
  def unsubscribe_run(run_id) do
    PubSub.unsubscribe(@pubsub, run_topic(run_id))
  end

  @doc """
  Unsubscribe from global events.
  """
  @spec unsubscribe_global() :: :ok | {:error, term()}
  def unsubscribe_global do
    PubSub.unsubscribe(@pubsub, global_topic())
  end

  # ============================================================================
  # Broadcast Events
  # ============================================================================

  @doc """
  Broadcast an event to all relevant topics.

  The event is broadcast to:
  - The run topic (if run_id is present)
  - The session topic (if session_id is present)
  - The global topic (always)

  ## Options

    * `:store` - Whether to store the event in EventStore. Default: true
  """
  @spec broadcast_event(map(), keyword()) :: :ok
  def broadcast_event(event, opts \\ []) do
    # Store event first if requested (default true)
    if Keyword.get(opts, :store, true) do
      CodePuppyControl.EventStore.store(event)
    end

    # Broadcast to run topic
    if run_id = event[:run_id] || event["run_id"] do
      PubSub.broadcast(@pubsub, run_topic(run_id), {:event, event})
    end

    # Broadcast to session topic
    if session_id = event[:session_id] || event["session_id"] do
      PubSub.broadcast(@pubsub, session_topic(session_id), {:event, event})
    end

    # Always broadcast to global
    PubSub.broadcast(@pubsub, global_topic(), {:event, event})

    :ok
  end

  @doc """
  Broadcast an event only to the local node (non-distributed).
  """
  @spec broadcast_local_event(map()) :: :ok
  def broadcast_local_event(event) do
    if run_id = event[:run_id] || event["run_id"] do
      PubSub.local_broadcast(@pubsub, run_topic(run_id), {:event, event})
    end

    if session_id = event[:session_id] || event["session_id"] do
      PubSub.local_broadcast(@pubsub, session_topic(session_id), {:event, event})
    end

    PubSub.local_broadcast(@pubsub, global_topic(), {:event, event})

    :ok
  end

  # ============================================================================
  # Event Type Helpers
  # ============================================================================

  @doc """
  Broadcast a text/content event from an agent.
  """
  @spec broadcast_text(String.t(), String.t() | nil, String.t(), keyword()) :: :ok
  def broadcast_text(run_id, session_id, content, opts \\ []) do
    event = %{
      type: "text",
      run_id: run_id,
      session_id: session_id,
      content: content,
      chunk: Keyword.get(opts, :chunk, false),
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a status update event.
  """
  @spec broadcast_status(String.t(), String.t() | nil, atom() | String.t(), keyword()) :: :ok
  def broadcast_status(run_id, session_id, status, opts \\ []) do
    event = %{
      type: "status",
      run_id: run_id,
      session_id: session_id,
      status: to_string(status),
      metadata: Keyword.get(opts, :metadata, %{}),
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a tool execution result.
  """
  @spec broadcast_tool_result(String.t(), String.t() | nil, String.t(), map(), keyword()) ::
          :ok
  def broadcast_tool_result(run_id, session_id, tool_name, result, opts \\ []) do
    event = %{
      type: "tool_result",
      run_id: run_id,
      session_id: session_id,
      tool_name: tool_name,
      result: result,
      tool_call_id: Keyword.get(opts, :tool_call_id),
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a tool call (request to execute a tool).
  """
  @spec broadcast_tool_call(String.t(), String.t() | nil, String.t(), map(), keyword()) :: :ok
  def broadcast_tool_call(run_id, session_id, tool_name, arguments, opts \\ []) do
    event = %{
      type: "tool_call",
      run_id: run_id,
      session_id: session_id,
      tool_name: tool_name,
      arguments: arguments,
      tool_call_id: Keyword.get(opts, :tool_call_id),
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a thinking/reasoning event.
  """
  @spec broadcast_thinking(String.t(), String.t() | nil, String.t(), keyword()) :: :ok
  def broadcast_thinking(run_id, session_id, content, opts \\ []) do
    event = %{
      type: "thinking",
      run_id: run_id,
      session_id: session_id,
      content: content,
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast an error event.
  """
  @spec broadcast_error(String.t(), String.t() | nil, String.t(), map(), keyword()) :: :ok
  def broadcast_error(run_id, session_id, message, details \\ %{}, opts \\ []) do
    event = %{
      type: "error",
      run_id: run_id,
      session_id: session_id,
      message: message,
      details: details,
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a run completion event.
  """
  @spec broadcast_completed(String.t(), String.t() | nil, map(), keyword()) :: :ok
  def broadcast_completed(run_id, session_id, result \\ %{}, opts \\ []) do
    event = %{
      type: "completed",
      run_id: run_id,
      session_id: session_id,
      result: result,
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a run failure event.
  """
  @spec broadcast_failed(String.t(), String.t() | nil, String.t(), map(), keyword()) :: :ok
  def broadcast_failed(run_id, session_id, error, details \\ %{}, opts \\ []) do
    event = %{
      type: "failed",
      run_id: run_id,
      session_id: session_id,
      error: error,
      details: details,
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a prompt/request for user input.
  """
  @spec broadcast_prompt(String.t(), String.t() | nil, String.t(), map(), keyword()) :: :ok
  def broadcast_prompt(run_id, session_id, prompt_id, prompt_data, opts \\ []) do
    event = %{
      type: "prompt",
      run_id: run_id,
      session_id: session_id,
      prompt_id: prompt_id,
      data: prompt_data,
      timestamp: DateTime.utc_now()
    }

    broadcast_event(event, opts)
  end

  @doc """
  Broadcast a heartbeat/keepalive event.
  """
  @spec broadcast_heartbeat(String.t(), String.t() | nil, map()) :: :ok
  def broadcast_heartbeat(run_id, session_id, metrics \\ %{}) do
    event = %{
      type: "heartbeat",
      run_id: run_id,
      session_id: session_id,
      metrics: metrics,
      timestamp: DateTime.utc_now()
    }

    # Heartbeats are not stored to avoid flooding the event store
    broadcast_event(event, store: false)
  end
end
