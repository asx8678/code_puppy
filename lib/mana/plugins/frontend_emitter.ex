defmodule Mana.Plugins.FrontendEmitter do
  @moduledoc """
  Plugin that forwards agent events to web frontends via Phoenix.PubSub.

  Broadcasts tool call events, streaming events, and agent invocations
  to subscribed web clients for real-time UI updates.

  ## Events Emitted

  - `"tool_call_start"` — Before a tool executes
  - `"tool_call_complete"` — After a tool finishes
  - `"stream_event"` — Real-time streaming chunks
  - `"agent_invoked"` — When a sub-agent is called

  ## Hooks Registered

  - `:pre_tool_call` — Emit tool call start event
  - `:post_tool_call` — Emit tool call complete event
  - `:stream_event` — Forward streaming events
  - `:invoke_agent` — Emit agent invocation event

  ## Configuration

      config :mana, Mana.Plugin.Manager,
        plugin_configs: %{
          Mana.Plugins.FrontendEmitter => %{
            pubsub_name: :mana_pubsub,       # PubSub name (default)
            topic_prefix: "events:",         # Topic prefix (default)
            sanitize_args: true              # Truncate large args (default)
          }
        }

  ## Usage

  Web clients subscribe to events:

      Phoenix.PubSub.subscribe(:mana_pubsub, "events:session_123")
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  @default_pubsub :mana_pubsub
  @default_topic_prefix "events:"
  @max_arg_length 500
  @max_event_data_length 1000

  # ── Plugin Behaviour ──────────────────────────────────────────────────────

  @impl true
  def name, do: "frontend_emitter"

  @impl true
  def init(config) do
    state = %{
      pubsub: Map.get(config, :pubsub_name, @default_pubsub),
      topic_prefix: Map.get(config, :topic_prefix, @default_topic_prefix),
      sanitize: Map.get(config, :sanitize_args, true),
      config: config
    }

    Logger.info("FrontendEmitter plugin initialized")
    {:ok, state}
  end

  @impl true
  def hooks do
    [
      {:pre_tool_call, &__MODULE__.on_pre_tool_call/3},
      {:post_tool_call, &__MODULE__.on_post_tool_call/5},
      {:stream_event, &__MODULE__.on_stream_event/3},
      {:invoke_agent, &__MODULE__.on_invoke_agent/2}
    ]
  end

  @impl true
  def terminate, do: :ok

  # ── Hook Handlers ─────────────────────────────────────────────────────────

  @doc """
  Emits a tool_call_start event before a tool executes.
  """
  @spec on_pre_tool_call(String.t(), map(), map()) :: :ok
  def on_pre_tool_call(tool_name, tool_args, _context) do
    emit("tool_call_start", %{
      tool_name: tool_name,
      tool_args: sanitize_args(tool_args),
      start_time: System.system_time(:millisecond)
    })

    Logger.debug("[FrontendEmitter] Emitted tool_call_start for #{tool_name}")
    :ok
  rescue
    e ->
      Logger.error("[FrontendEmitter] Failed to emit pre_tool_call: #{inspect(e)}")
      :ok
  end

  @doc """
  Emits a tool_call_complete event after a tool finishes.
  """
  @spec on_post_tool_call(String.t(), map(), term(), number(), map()) :: :ok
  def on_post_tool_call(tool_name, tool_args, result, duration_ms, _context) do
    emit("tool_call_complete", %{
      tool_name: tool_name,
      tool_args: sanitize_args(tool_args),
      duration_ms: duration_ms,
      success: is_successful?(result),
      result_summary: summarize_result(result)
    })

    Logger.debug("[FrontendEmitter] Emitted tool_call_complete for #{tool_name} (#{duration_ms}ms)")
    :ok
  rescue
    e ->
      Logger.error("[FrontendEmitter] Failed to emit post_tool_call: #{inspect(e)}")
      :ok
  end

  @doc """
  Forwards streaming events to web clients.
  """
  @spec on_stream_event(String.t(), term(), String.t() | nil) :: :ok
  def on_stream_event(event_type, event_data, session_id) do
    emit(
      "stream_event",
      %{
        event_type: event_type,
        event_data: sanitize_event_data(event_data),
        agent_session_id: session_id
      },
      session_id
    )

    Logger.debug("[FrontendEmitter] Emitted stream_event: #{event_type}")
    :ok
  rescue
    e ->
      Logger.error("[FrontendEmitter] Failed to emit stream_event: #{inspect(e)}")
      :ok
  end

  @doc """
  Emits an agent_invoked event when a sub-agent is called.
  """
  @spec on_invoke_agent(term(), term()) :: :ok
  def on_invoke_agent(args, kwargs) do
    agent_info = %{
      agent_name: extract_name(args, kwargs),
      session_id: extract_session(args, kwargs),
      prompt_preview: extract_prompt(args, kwargs) |> truncate(@max_arg_length)
    }

    emit("agent_invoked", agent_info)

    Logger.debug("[FrontendEmitter] Emitted agent_invoked: #{agent_info.agent_name}")
    :ok
  rescue
    e ->
      Logger.error("[FrontendEmitter] Failed to emit invoke_agent: #{inspect(e)}")
      :ok
  end

  # ── Event Emission ────────────────────────────────────────────────────────

  @doc """
  Broadcasts an event via Phoenix.PubSub.

  Falls back gracefully if PubSub is not available.
  """
  @spec emit(String.t(), map(), String.t() | nil) :: :ok
  def emit(event_type, data, session_id \\ nil) do
    pubsub = get_pubsub()
    topic = build_topic(session_id)

    message = %{
      type: event_type,
      data: data,
      timestamp: System.system_time(:millisecond)
    }

    try do
      Phoenix.PubSub.broadcast(pubsub, topic, {:frontend_event, message})
    rescue
      _ ->
        Logger.debug("[FrontendEmitter] PubSub not available — event dropped")
    catch
      :exit, _ ->
        Logger.debug("[FrontendEmitter] PubSub not started — event dropped")
    end

    :ok
  end

  # ── Data Sanitization ─────────────────────────────────────────────────────

  defp sanitize_args(args) when is_map(args) do
    Map.new(args, fn {key, value} ->
      {key, sanitize_value(value)}
    end)
  end

  defp sanitize_args(args), do: args

  defp sanitize_value(value) when is_binary(value) do
    truncate(value, @max_arg_length)
  end

  defp sanitize_value(value) when is_number(value) or is_boolean(value) or is_nil(value) do
    value
  end

  defp sanitize_value(value) when is_list(value) or is_map(value) do
    "<collection[#{if is_list(value), do: length(value), else: map_size(value)}]>"
  end

  defp sanitize_value(value), do: "<#{inspect(value.__struct__)}>"

  defp sanitize_event_data(data) when is_binary(data) do
    truncate(data, @max_event_data_length)
  end

  defp sanitize_event_data(data) when is_number(data) or is_boolean(data) or is_nil(data) do
    data
  end

  defp sanitize_event_data(data) when is_map(data) do
    data
    |> Enum.take(20)
    |> Map.new(fn {k, v} -> {k, sanitize_event_data(v)} end)
  end

  defp sanitize_event_data(data) when is_list(data) do
    Enum.take(data, 20) |> Enum.map(&sanitize_event_data/1)
  end

  defp sanitize_event_data(data), do: truncate(inspect(data, limit: 50), @max_event_data_length)

  # ── Result Helpers ────────────────────────────────────────────────────────

  defp is_successful?(nil), do: true
  defp is_successful?(result) when is_map(result), do: not (Map.get(result, :error) || Map.get(result, "error"))
  defp is_successful?(result) when is_boolean(result), do: result
  defp is_successful?(_), do: true

  defp summarize_result(nil), do: "<no result>"

  defp summarize_result(result) when is_binary(result) do
    truncate(result, 200)
  end

  defp summarize_result(result) when is_map(result) do
    if Map.has_key?(result, :error) or Map.has_key?(result, "error") do
      error = Map.get(result, :error) || Map.get(result, "error")
      "Error: #{truncate(to_string(error), 100)}"
    else
      "<map with #{map_size(result)} keys>"
    end
  end

  defp summarize_result(result) when is_list(result) do
    "<list[#{length(result)}]>"
  end

  defp summarize_result(result), do: truncate(inspect(result, limit: 50), 200)

  # ── Arg Extraction for invoke_agent ───────────────────────────────────────

  defp extract_name(args, _kwargs) when is_list(args) and length(args) > 0, do: to_string(hd(args))
  defp extract_name(_args, kwargs) when is_list(kwargs), do: extract_kw(kwargs, :agent_name)
  defp extract_name(_args, kwargs) when is_map(kwargs), do: Map.get(kwargs, :agent_name)
  defp extract_name(_, _), do: nil

  defp extract_session(args, _kwargs) when is_list(args) and length(args) > 1, do: to_string(Enum.at(args, 1))
  defp extract_session(_args, kwargs) when is_list(kwargs), do: extract_kw(kwargs, :session_id)
  defp extract_session(_args, kwargs) when is_map(kwargs), do: Map.get(kwargs, :session_id)
  defp extract_session(_, _), do: nil

  defp extract_prompt(args, _kwargs) when is_list(args) and length(args) > 2, do: to_string(Enum.at(args, 2))
  defp extract_prompt(_args, kwargs) when is_list(kwargs), do: extract_kw(kwargs, :prompt)
  defp extract_prompt(_args, kwargs) when is_map(kwargs), do: Map.get(kwargs, :prompt)
  defp extract_prompt(_, _), do: nil

  defp extract_kw(kwargs, key) do
    case List.keyfind(kwargs, key, 0) do
      {^key, value} -> to_string(value)
      nil -> nil
    end
  end

  # ── Misc Helpers ──────────────────────────────────────────────────────────

  defp truncate(string, max_len) when is_binary(string) do
    if byte_size(string) > max_len do
      String.slice(string, 0, max_len) <> "..."
    else
      string
    end
  end

  defp truncate(other, max_len), do: truncate(inspect(other), max_len)

  defp get_pubsub do
    Application.get_env(:mana, __MODULE__, [])
    |> Keyword.get(:pubsub_name, @default_pubsub)
  end

  defp build_topic(nil), do: "#{topic_prefix()}all"
  defp build_topic(session_id), do: "#{topic_prefix()}#{session_id}"

  defp topic_prefix do
    Application.get_env(:mana, __MODULE__, [])
    |> Keyword.get(:topic_prefix, @default_topic_prefix)
  end
end
