defmodule Mana.Plugins.Logger do
  @moduledoc """
  Built-in plugin that logs agent lifecycle events and tool calls.

  This plugin demonstrates the Mana plugin system by implementing
  the `Mana.Plugin.Behaviour` and registering for various hooks.

  ## Configuration

      config :mana, Mana.Plugin.Manager,
        plugins: [:discover, Mana.Plugins.Logger],
        plugin_configs: %{
          Mana.Plugins.Logger => %{
            level: :info,           # :debug | :info | :warn | :error
            log_tool_calls: true,
            log_stream_events: false
          }
        }

  ## Hooks Registered

  - `:startup` - Log when the system starts
  - `:agent_run_start` - Log when an agent run begins
  - `:agent_run_end` - Log when an agent run completes
  - `:pre_tool_call` - Log tool calls (if enabled)
  - `:post_tool_call` - Log tool results (if enabled)
  - `:stream_event` - Log streaming events (if enabled)
  - `:shutdown` - Log when the system shuts down
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger



  @impl true
  def name, do: "logger"

  @impl true
  def init(config) do
    level = Map.get(config, :level, :info)
    log_tool_calls = Map.get(config, :log_tool_calls, true)
    log_stream_events = Map.get(config, :log_stream_events, false)

    # Configure Elixir Logger level for this plugin's namespace
    Logger.put_module_level(__MODULE__, level)

    state = %{
      level: level,
      log_tool_calls: log_tool_calls,
      log_stream_events: log_stream_events,
      run_count: 0,
      tool_count: 0
    }

    Logger.info("Logger plugin initialized with level: #{level}")
    {:ok, state}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.on_startup/0},
      {:agent_run_start, &__MODULE__.on_agent_run_start/3},
      {:agent_run_end, &__MODULE__.on_agent_run_end/7},
      {:pre_tool_call, &__MODULE__.on_pre_tool_call/3},
      {:post_tool_call, &__MODULE__.on_post_tool_call/5},
      {:stream_event, &__MODULE__.on_stream_event/3},
      {:shutdown, &__MODULE__.on_shutdown/0}
    ]
  end

  @impl true
  def terminate do
    Logger.info("Logger plugin shutting down")
    :ok
  end

  @doc false
  def on_startup do
    Logger.info("Mana system starting up")
    :ok
  end

  @doc false
  def on_agent_run_start(agent_name, model_name, session_id) do
    session = session_id || "no-session"
    Logger.info("Agent run started: #{agent_name} (model: #{model_name}, session: #{session})")
    :ok
  end

  @doc false
  def on_agent_run_end(agent_name, model_name, session_id, success, error, _response_text, _metadata) do
    session = session_id || "no-session"

    if success do
      Logger.info("Agent run completed: #{agent_name} (model: #{model_name}, session: #{session})")
    else
      error_msg = if error, do: " error: #{inspect(error)}", else: ""
      Logger.warning("Agent run failed: #{agent_name} (model: #{model_name}, session: #{session})#{error_msg}")
    end

    :ok
  end

  @doc false
  def on_pre_tool_call(tool_name, tool_args, _context) do
    # Only log at debug level to avoid spam
    args_summary = summarize_args(tool_args)
    Logger.debug("Tool call: #{tool_name}(#{args_summary})")
    :ok
  end

  @doc false
  def on_post_tool_call(tool_name, _tool_args, result, duration_ms, _context) do
    result_summary = summarize_result(result)
    Logger.debug("Tool completed: #{tool_name} in #{duration_ms}ms -> #{result_summary}")
    :ok
  end

  @doc false
  def on_stream_event(event_type, event_data, session_id) do
    session = session_id || "no-session"
    Logger.debug("Stream event [#{session}]: #{event_type} - #{inspect(event_data, limit: 100)}")
    :ok
  end

  @doc false
  def on_shutdown do
    Logger.info("Mana system shutting down")
    :ok
  end

  # Private helpers

  defp summarize_args(args) when is_map(args) do
    keys = Map.keys(args) |> Enum.join(", ")
    "keys: [#{keys}]"
  end

  defp summarize_args(args) when is_list(args) do
    "count: #{length(args)}"
  end

  defp summarize_args(_args), do: "..."

  defp summarize_result(result) when is_binary(result) do
    if String.length(result) > 50 do
      String.slice(result, 0, 50) <> "..."
    else
      result
    end
  end

  defp summarize_result(result) when is_map(result) do
    keys = Map.keys(result) |> Enum.take(3) |> Enum.join(", ")
    "{#{keys}...}"
  end

  defp summarize_result(result) do
    inspect(result, limit: 50)
  end
end
