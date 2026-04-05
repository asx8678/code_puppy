defmodule Mana.Callbacks do
  @moduledoc """
  Convenience API for the callbacks system.

  Provides macro-generated `on_<phase>` functions for all available hook phases,
  plus delegation functions to the Registry.

  ## Usage

      # Dispatch using generated function
      Mana.Callbacks.on_startup()
      Mana.Callbacks.on_agent_run_start("my_agent", "gpt-4", "session_123")

      # Register/unregister callbacks
      Mana.Callbacks.register(:startup, &MyMod.on_startup/0)
      Mana.Callbacks.unregister(:startup, &MyMod.on_startup/0)
      Mana.Callbacks.clear(:startup)

  The generated functions automatically build the correct argument list
  based on the hook phase definition from `Mana.Plugin.Hook`.
  """

  alias Mana.Callbacks.Registry
  alias Mana.Plugin.Hook

  # Generate on_<phase> functions for all hooks
  # This macro runs at compile time to generate all dispatch functions

  hooks_metadata = Hook.hooks_metadata()

  # Generate on_<phase> functions for each hook
  for {phase, metadata} <- hooks_metadata do
    arity = metadata.arity
    async = metadata.async

    # Build argument list based on arity
    args =
      case arity do
        0 ->
          []

        1 ->
          [quote(do: arg1)]

        2 ->
          [quote(do: arg1), quote(do: arg2)]

        3 ->
          [quote(do: arg1), quote(do: arg2), quote(do: arg3)]

        4 ->
          [quote(do: arg1), quote(do: arg2), quote(do: arg3), quote(do: arg4)]

        5 ->
          [quote(do: arg1), quote(do: arg2), quote(do: arg3), quote(do: arg4), quote(do: arg5)]

        6 ->
          [quote(do: arg1), quote(do: arg2), quote(do: arg3), quote(do: arg4), quote(do: arg5), quote(do: arg6)]

        7 ->
          [
            quote(do: arg1),
            quote(do: arg2),
            quote(do: arg3),
            quote(do: arg4),
            quote(do: arg5),
            quote(do: arg6),
            quote(do: arg7)
          ]

        _ ->
          []
      end

    # Build the doc string
    doc_string = """
    Dispatches to all registered #{phase} callbacks.

    Expected signature: #{Hook.callback_signature(phase)}
    Async: #{async}
    """

    # Define the function
    @doc doc_string
    def unquote(:"on_#{phase}")(unquote_splicing(args)) do
      Registry.dispatch(unquote(phase), unquote(args))
    end
  end

  @doc """
  Registers a callback for a phase.

  ## Examples

      Mana.Callbacks.register(:startup, &MyMod.on_startup/0)
      :ok
  """
  @spec register(atom(), fun()) :: :ok | {:error, term()}
  def register(phase, callback) do
    Registry.register(phase, callback)
  end

  @doc """
  Unregisters a callback for a phase.

  ## Examples

      Mana.Callbacks.unregister(:startup, &MyMod.on_startup/0)
      :ok
  """
  @spec unregister(atom(), fun()) :: :ok | {:error, term()}
  def unregister(phase, callback) do
    Registry.unregister(phase, callback)
  end

  @doc """
  Clears all callbacks for a phase.

  ## Examples

      Mana.Callbacks.clear(:startup)
      :ok
  """
  @spec clear(atom()) :: :ok
  def clear(phase) do
    Registry.clear(phase)
  end

  @doc """
  Dispatches to all callbacks for a phase with the given arguments.

  ## Examples

      Mana.Callbacks.dispatch(:startup, [])
      {:ok, [:ok, :ok]}
  """
  @spec dispatch(atom(), list()) :: {:ok, list()} | {:error, term()}
  def dispatch(phase, args \\ []) do
    Registry.dispatch(phase, args)
  end

  @doc """
  Triggers callbacks for a phase (alias for dispatch/2).

  ## Examples

      Mana.Callbacks.trigger(:startup, [])
      {:ok, [:ok, :ok]}
  """
  @spec trigger(atom(), list()) :: {:ok, list()} | {:error, term()}
  def trigger(phase, args \\ []) do
    Registry.dispatch(phase, args)
  end

  @doc """
  Returns all callbacks registered for a phase.

  ## Examples

      Mana.Callbacks.get_callbacks(:startup)
      [&MyMod.on_startup/0]
  """
  @spec get_callbacks(atom()) :: list(fun())
  def get_callbacks(phase) do
    Registry.get_callbacks(phase)
  end

  @doc """
  Drains (retrieves and clears) the backlog for a phase.

  ## Examples

      Mana.Callbacks.drain_backlog(:startup)
      {:ok, [%{args: [], timestamp: 12345}]}
  """
  @spec drain_backlog(atom()) :: {:ok, list(map())} | {:error, term()}
  def drain_backlog(phase) do
    Registry.drain_backlog(phase)
  end

  @doc """
  Returns current registry statistics.

  ## Examples

      Mana.Callbacks.get_stats()
      %{dispatches: 10, errors: 0, callbacks_registered: 5, backlog_size: 0}
  """
  @spec get_stats() :: map()
  def get_stats do
    Registry.get_stats()
  end
end
