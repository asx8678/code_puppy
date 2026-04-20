defmodule CodePuppyControl.Callbacks do
  @moduledoc """
  Public API for the callback registry and trigger system.

  This module is the primary interface for registering, unregistering,
  and triggering callback hooks. It delegates storage to the
  `CodePuppyControl.Callbacks.Registry` GenServer and merge logic to
  `CodePuppyControl.Callbacks.Merge`.

  ## Quick Start

      # Register a callback
      CodePuppyControl.Callbacks.register(:startup, fn ->
        IO.puts("Application started!")
      end)

      # Trigger callbacks for a hook
      CodePuppyControl.Callbacks.trigger(:startup)

      # Unregister
      CodePuppyControl.Callbacks.unregister(:startup, my_fun)

  ## Merge Semantics

  When multiple callbacks are registered for a hook, their results
  are merged according to the hook's declared strategy:

  - `:concat_str` — string results concatenated with newlines
  - `:extend_list` — list results flattened into one list
  - `:update_map` — map results deep-merged (later wins)
  - `:or_bool` — boolean results OR'd (any true wins)
  - `:noop` — results collected as-is

  ## Error Handling

  If a callback raises an exception, it is caught and replaced with
  the `:callback_failed` sentinel. The host process is never killed.
  Failed callbacks are logged at the `:error` level.
  """

  require Logger

  alias CodePuppyControl.Callbacks.{Hooks, Merge, Registry}

  # ── Registration ────────────────────────────────────────────────

  @doc """
  Registers a callback function for the given hook.

  Idempotent: registering the same function twice for the same hook
  is a no-op. Callbacks execute in registration order.

  Raises `ArgumentError` if the hook name is not a known hook.

  ## Examples

      CodePuppyControl.Callbacks.register(:startup, fn -> IO.puts("started") end)
  """
  @spec register(atom(), function()) :: :ok
  def register(hook_name, fun) when is_atom(hook_name) and is_function(fun) do
    unless Hooks.valid?(hook_name) do
      raise ArgumentError,
            "Unknown hook: #{inspect(hook_name)}. Known hooks: #{inspect(Hooks.names())}"
    end

    Registry.register(hook_name, fun)
  end

  @doc """
  Unregisters a callback function from the given hook.

  Returns `true` if the callback was found and removed, `false` otherwise.

  ## Examples

      CodePuppyControl.Callbacks.unregister(:startup, my_fun)
  """
  @spec unregister(atom(), function()) :: boolean()
  def unregister(hook_name, fun) when is_atom(hook_name) and is_function(fun) do
    Registry.unregister(hook_name, fun)
  end

  # ── Triggering ──────────────────────────────────────────────────

  @doc """
  Triggers all callbacks registered for the given hook (synchronously).

  Callbacks execute in registration order. Results are merged according
  to the hook's declared merge strategy. Failed callbacks are replaced
  with `:callback_failed` and logged.

  Returns the merged result, or `nil` if no callbacks are registered.

  ## Examples

      CodePuppyControl.Callbacks.trigger(:load_prompt)
      #=> "plugin1 instructions\\nplugin2 instructions"
  """
  @spec trigger(atom(), [term()]) :: term()
  def trigger(hook_name, args \\ []) when is_atom(hook_name) and is_list(args) do
    callbacks = Registry.get_callbacks(hook_name)

    if callbacks == [] do
      nil
    else
      results = execute_callbacks(hook_name, callbacks, args)
      merge_strategy = Hooks.merge_type(hook_name)
      Merge.merge_results(results, merge_strategy)
    end
  end

  @doc """
  Triggers all callbacks registered for the given hook concurrently.

  All callbacks are spawned as separate tasks and awaited. Results are
  collected in registration order (not completion order), then merged
  according to the hook's declared merge strategy.

  Only appropriate for hooks declared with `async: true` in `Hooks`.

  Returns `{:ok, merged_result}` or `{:error, :not_async}` if the hook
  doesn't support async execution.

  ## Examples

      CodePuppyControl.Callbacks.trigger_async(:stream_event, ["token", data, session_id])
      #=> {:ok, nil}
  """
  @spec trigger_async(atom(), [term()]) :: {:ok, term()} | {:error, :not_async}
  def trigger_async(hook_name, args \\ []) when is_atom(hook_name) and is_list(args) do
    if Hooks.async?(hook_name) do
      callbacks = Registry.get_callbacks(hook_name)

      if callbacks == [] do
        {:ok, nil}
      else
        results = execute_callbacks_async(hook_name, callbacks, args)
        merge_strategy = Hooks.merge_type(hook_name)
        {:ok, Merge.merge_results(results, merge_strategy)}
      end
    else
      {:error, :not_async}
    end
  end

  # ── Python-Compatible Alias ─────────────────────────────────────

  @doc """
  Triggers all callbacks for a hook (alias for `trigger/2`).

  This provides a Python-compatible API matching the `on(hook, args)`
  pattern from `code_puppy.callbacks`.

  ## Examples

      CodePuppyControl.Callbacks.on(:startup)
      CodePuppyControl.Callbacks.on(:custom_command, ["/echo hello", "echo"])
  """
  @spec on(atom(), [term()]) :: term()
  def on(hook_name, args \\ []) when is_atom(hook_name) and is_list(args) do
    trigger(hook_name, args)
  end

  # ── Introspection ───────────────────────────────────────────────

  @doc """
  Returns the number of callbacks registered for a hook.

  Pass `:all` to get the total count across all hooks.

  ## Examples

      CodePuppyControl.Callbacks.count_callbacks(:startup)
      #=> 3

      CodePuppyControl.Callbacks.count_callbacks(:all)
      #=> 12
  """
  @spec count_callbacks(atom()) :: non_neg_integer()
  def count_callbacks(hook_name \\ :all) when is_atom(hook_name) do
    Registry.count(hook_name)
  end

  @doc """
  Returns a list of hook names that have at least one callback registered.
  """
  @spec active_hooks() :: [atom()]
  def active_hooks do
    Registry.active_hooks()
  end

  @doc """
  Returns the ordered list of callbacks for a hook (for debugging).
  """
  @spec get_callbacks(atom()) :: [function()]
  def get_callbacks(hook_name) when is_atom(hook_name) do
    Registry.get_callbacks(hook_name)
  end

  @doc """
  Removes all callbacks for a hook, or all hooks if `:all` is passed.

  Primarily used in test teardown for isolation.
  """
  @spec clear(atom() | nil) :: :ok
  def clear(hook_name \\ nil) do
    Registry.clear(hook_name)
  end

  # ── Private Helpers ─────────────────────────────────────────────

  @doc false
  @spec execute_callbacks(atom(), [function()], [term()]) :: [term()]
  defp execute_callbacks(hook_name, callbacks, args) do
    Enum.map(callbacks, fn callback ->
      try do
        apply(callback, args)
      rescue
        e ->
          Logger.error(
            "Callback #{inspect(callback)} failed in hook :#{hook_name}: " <>
              Exception.message(e) <> "\n" <> Exception.format_stacktrace(__STACKTRACE__)
          )

          Merge.error_sentinel()
      catch
        kind, reason ->
          Logger.error(
            "Callback #{inspect(callback)} crashed in hook :#{hook_name}: " <>
              Exception.format(kind, reason, __STACKTRACE__)
          )

          Merge.error_sentinel()
      end
    end)
  end

  @doc false
  @spec execute_callbacks_async(atom(), [function()], [term()]) :: [term()]
  defp execute_callbacks_async(hook_name, callbacks, args) do
    # Spawn all callbacks as tasks, preserving registration order in results
    tasks =
      Enum.map(callbacks, fn callback ->
        Task.async(fn ->
          try do
            apply(callback, args)
          rescue
            e ->
              Logger.error(
                "Async callback #{inspect(callback)} failed in hook :#{hook_name}: " <>
                  Exception.message(e)
              )

              Merge.error_sentinel()
          catch
            kind, reason ->
              Logger.error(
                "Async callback #{inspect(callback)} crashed in hook :#{hook_name}: " <>
                  Exception.format(kind, reason, __STACKTRACE__)
              )

              Merge.error_sentinel()
          end
        end)
      end)

    # Await all tasks — order preserved because we zip with callbacks
    Enum.map(tasks, fn task ->
      try do
        Task.await(task, 5_000)
      catch
        :exit, {:timeout, _} ->
          Logger.error("Async callback timed out in hook :#{hook_name}")
          Merge.error_sentinel()

        :exit, {reason, _} ->
          Logger.error("Async callback exited in hook :#{hook_name}: #{inspect(reason)}")
          Merge.error_sentinel()
      end
    end)
  end
end
