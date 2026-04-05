defmodule Mana.TTSR do
  @moduledoc """
  Triggered Time-Traveling Streamed Rules — unique intelligence feature.

  TTSR watches streaming LLM output for regex patterns and injects
  contextual rules into the next turn's system prompt.

  ## Features

  - **Per-scope watching**: text, thinking, tool, or all streams
  - **Ring buffer safety**: 512-char sliding window catches patterns
    that straddle SSE chunk boundaries
  - **Repeat policies**: :once (trigger once) or {:gap, N} (repeat every N turns)
  - **Markdown rule files**: YAML frontmatter + content body

  ## Rule File Format

  Rules are loaded from `~/.mana/rules/*.md` and `./rules/*.md`:

      ---
      name: error-watcher
      trigger: "error|exception|failed"
      scope: text
      repeat: once
      ---

      When you see an error, suggest looking at the logs for
      more detailed debugging information.

  ## Hooks

  - `:startup` - Load rules and start registry
  - `:stream_event` - Watch stream chunks for triggers
  - `:agent_run_end` - Increment turn counter
  - `:load_prompt` - Inject pending rules (future integration)
  - `:custom_command` - `/ttsr list` command
  """

  @behaviour Mana.Plugin.Behaviour

  alias Mana.TTSR.{RuleLoader, StreamWatcher}

  @persistent_term_key {__MODULE__, :rules}

  @impl true
  def name, do: "ttsr"

  @impl true
  def init(_config) do
    # Load rules and store in persistent_term
    rules = RuleLoader.load()
    :persistent_term.put(@persistent_term_key, rules)

    {:ok, %{rules: rules}}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.on_startup/0},
      {:stream_event, &__MODULE__.on_stream_event/3},
      {:load_prompt, &__MODULE__.on_load_prompt/0},
      {:agent_run_end, &__MODULE__.on_agent_run_end/7},
      {:custom_command, &__MODULE__.handle_command/2}
    ]
  end

  @impl true
  def terminate do
    :ok
  end

  @doc """
  Startup hook - initializes the TTSR system.
  """
  def on_startup do
    # Rules are already loaded in init/1, this hook can be used
    # for additional startup tasks if needed
    :ok
  end

  @doc """
  Stream event hook - watches for trigger patterns.
  """
  def on_stream_event(event_type, event_data, session_id) do
    rules = :persistent_term.get(@persistent_term_key, [])

    case find_or_start_watcher(session_id, rules) do
      {:ok, _pid} ->
        StreamWatcher.watch_event(session_id, {event_type, event_data})

      _ ->
        :ok
    end
  end

  @doc """
  Load prompt hook - returns content from pending rules.
  Called each turn to assemble system prompt additions.
  """
  def on_load_prompt do
    # This is called per-turn to get any pending rule content.
    # The actual injection happens via the agent runner's prompt assembly.
    nil
  end

  @doc """
  Agent run end hook - increments turn counter.
  """
  def on_agent_run_end(_agent_name, _model_name, session_id, _success, _error, _response, _meta) do
    StreamWatcher.increment_turn(session_id)
    StreamWatcher.stop(session_id)
    :ok
  end

  @doc """
  Custom command handler for /ttsr commands.
  """
  def handle_command("ttsr", ["list"]) do
    rules = :persistent_term.get(@persistent_term_key, [])
    format_rule_list(rules)
  end

  def handle_command("ttsr", ["status" | session_id]) do
    sid = List.first(session_id) || "default"
    format_session_status(sid)
  end

  def handle_command("ttsr", _) do
    """
    Usage: /ttsr <command>

    Commands:
      list              - Show loaded rules
      status [session]  - Show watcher status for session
    """
  end

  def handle_command(_, _), do: nil

  # Private functions

  defp format_rule_list([]) do
    "No TTSR rules loaded.\n\nRules are loaded from ~/.mana/rules/*.md and ./rules/*.md"
  end

  defp format_rule_list(rules) do
    header = "Loaded TTSR rules:\n"

    lines =
      Enum.map(rules, fn rule ->
        repeat_str =
          case rule.repeat do
            :once -> "once"
            {:gap, n} -> "gap:#{n}"
          end

        "  • #{rule.name} [#{rule.scope}] (#{repeat_str})\n    Trigger: #{inspect(rule.trigger)}"
      end)

    header <> Enum.join(lines, "\n")
  end

  defp format_session_status(sid) do
    case StreamWatcher.find_watcher(sid) do
      nil ->
        "No active watcher for session '#{sid}'"

      pid when is_pid(pid) ->
        pending = StreamWatcher.get_pending(sid)
        format_pending_status(sid, pending)
    end
  end

  defp format_pending_status(sid, []) do
    "Session '#{sid}' active, no pending rules."
  end

  defp format_pending_status(sid, pending) do
    pending_lines = Enum.map_join(pending, "\n", fn r -> "  • #{r.name}" end)
    "Session '#{sid}' active, #{length(pending)} pending rule(s):\n" <> pending_lines
  end

  defp find_or_start_watcher(session_id, rules) do
    case Registry.lookup(Mana.TTSR.Registry, session_id) do
      [{pid, _}] ->
        {:ok, pid}

      [] ->
        case StreamWatcher.start_supervised(session_id, rules) do
          {:ok, pid} -> {:ok, pid}
          {:error, {:already_started, pid}} -> {:ok, pid}
          error -> error
        end
    end
  end
end
