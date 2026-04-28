defmodule CodePuppyControl.HookEngine.CallbackAdapter do
  @moduledoc """
  Integrates HookEngine into the existing CodePuppyControl.Callbacks system.

  This adapter registers itself as a `:pre_tool_call` and `:post_tool_call`
  callback so that any configured hook scripts run automatically when tools
  are invoked.

  ## Usage

      # One-time setup (typically in application startup):
      CodePuppyControl.HookEngine.CallbackAdapter.register(engine_pid)

  ## Callback Flow

  1. A tool is about to be called → `:pre_tool_call` fires
  2. The adapter constructs an `EventData` and runs `HookEngine.process_event/4`
  3. If the result is blocked, the adapter returns `%{blocked: true, reason: ...}`
  4. If not blocked, returns `nil` (pass-through)

  ## Python Semantics Preserved

  The merge semantics from `code_puppy/callbacks.py` are respected:
  - For `:pre_tool_call` (merge: `:noop`), the adapter returns either
    `%{blocked: true}` or `nil`, matching the Python `run_shell_command`
    hook pattern.
  - For `:post_tool_call` (merge: `:noop`), the adapter returns `nil`
    (observer only — post hooks cannot block).
  """

  require Logger

  alias CodePuppyControl.HookEngine
  alias CodePuppyControl.HookEngine.Models.EventData

  @doc """
  Registers the adapter as a `:pre_tool_call` and `:post_tool_call`
  callback with `CodePuppyControl.Callbacks`.

  `engine` is the PID or registered name of the `HookEngine` GenServer.
  If no engine is passed, defaults to `CodePuppyControl.HookEngine`.

  Idempotent — safe to call multiple times.
  """
  @spec register(GenServer.server()) :: :ok
  def register(engine \\ HookEngine) do
    # Stash engine ref in process dictionary so the closures
    # always point to the right process (even if restarted).
    pre_fn = fn tool_name, tool_args, _context ->
      handle_pre_tool_call(engine, tool_name, tool_args)
    end

    post_fn = fn tool_name, tool_args, _result, _duration_ms, _context ->
      handle_post_tool_call(engine, tool_name, tool_args)
    end

    CodePuppyControl.Callbacks.register(:pre_tool_call, pre_fn)
    CodePuppyControl.Callbacks.register(:post_tool_call, post_fn)

    :ok
  end

  @doc """
  Handles a `:pre_tool_call` event by processing it through the HookEngine.

  Returns `%{blocked: true, reason: "..."}` if any hook blocks, or `nil`
  to allow the operation.
  """
  @spec handle_pre_tool_call(GenServer.server(), String.t(), map()) ::
          %{blocked: true, reason: String.t()} | nil
  def handle_pre_tool_call(engine, tool_name, tool_args) do
    event_data =
      EventData.new(
        event_type: "PreToolUse",
        tool_name: tool_name,
        tool_args: tool_args
      )

    result = HookEngine.process_event(engine, "PreToolUse", event_data)

    if result.blocked do
      Logger.warning("PreToolUse hook blocked: #{result.blocking_reason}")
      %{blocked: true, reason: result.blocking_reason || "blocked by hook"}
    else
      nil
    end
  rescue
    e ->
      Logger.error("HookEngine pre_tool_call adapter error: #{Exception.message(e)}")
      # Fail-open: don't block on adapter errors
      nil
  catch
    :exit, _ ->
      # Engine process not alive — fail-open
      nil
  end

  @doc """
  Handles a `:post_tool_call` event by processing it through the HookEngine.

  Post hooks are observers only — they cannot block.
  Returns `nil` always.
  """
  @spec handle_post_tool_call(GenServer.server(), String.t(), map()) :: nil
  def handle_post_tool_call(engine, tool_name, tool_args) do
    event_data =
      EventData.new(
        event_type: "PostToolUse",
        tool_name: tool_name,
        tool_args: tool_args
      )

    _result = HookEngine.process_event(engine, "PostToolUse", event_data)
    nil
  rescue
    e ->
      Logger.error("HookEngine post_tool_call adapter error: #{Exception.message(e)}")
      nil
  catch
    :exit, _ ->
      nil
  end
end
