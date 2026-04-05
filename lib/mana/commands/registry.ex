defmodule Mana.Commands.Registry do
  @moduledoc """
  GenServer for command registration and dispatch.

  ## Features

  - Register command modules implementing `Mana.Commands.Behaviour`
  - Dispatch commands by name with fuzzy matching
  - Track command statistics
  - Support command aliases

  ## State Structure

  - `commands`: Map of command_name (string) => module
  - `aliases`: Map of alias => canonical_name
  - `stats`: Command execution statistics

  ## Usage

      # Start the registry
      Mana.Commands.Registry.start_link([])

      # Register a command
      Mana.Commands.Registry.register(Mana.Commands.Core.Help)

      # Dispatch a command
      Mana.Commands.Registry.dispatch("/help", [], %{})

      # List all commands
      Mana.Commands.Registry.list_commands()
  """

  use GenServer

  require Logger

  @table :mana_commands
  @max_levenshtein_distance 2

  # Client API

  @doc """
  Starts the Commands Registry GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Returns the child specification for supervision trees.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :permanent
    }
  end

  @doc """
  Registers a command module that implements the Behaviour.

  Returns `:ok` on success, `{:error, reason}` on failure.
  """
  @spec register(module()) :: :ok | {:error, term()}
  def register(command_module) do
    GenServer.call(__MODULE__, {:register, command_module})
  end

  @doc """
  Dispatches a command by name with the given arguments and context.

  Supports fuzzy matching if exact match fails.
  Returns the result of command execution.
  """
  @spec dispatch(String.t(), [String.t()], map()) ::
          :ok | {:ok, term()} | {:error, term()}
  def dispatch(command_name, args \\ [], context \\ %{}) do
    GenServer.call(__MODULE__, {:dispatch, command_name, args, context})
  end

  @doc """
  Lists all registered command names.
  """
  @spec list_commands() :: [String.t()]
  def list_commands do
    case :ets.whereis(@table) do
      :undefined -> []
      _table -> :ets.select(@table, [{{:"$1", :_}, [], [:"$1"]}]) |> Enum.sort()
    end
  end

  @doc """
  Gets command details (module, description, usage) for a command.

  Returns `{:ok, details}` or `{:error, :not_found}`.
  """
  @spec get_command(String.t()) :: {:ok, map()} | {:error, :not_found}
  def get_command(name) do
    case :ets.lookup(@table, name) do
      [{^name, info}] ->
        {:ok, %{name: name, description: info.description, usage: info.usage, module: info.module}}

      [] ->
        {:error, :not_found}
    end
  end

  @doc """
  Returns current registry statistics.
  """
  @spec get_stats() :: map()
  def get_stats do
    GenServer.call(__MODULE__, :get_stats)
  end

  @doc """
  Lists all registered command names (alias for list_commands/0).
  """
  @spec list() :: [String.t()]
  def list do
    list_commands()
  end

  @doc """
  Executes a command by name with the given arguments and context.

  Supports fuzzy matching if exact match fails.
  Returns the result of command execution.
  """
  @spec execute(String.t(), keyword() | map()) :: :ok | {:ok, term()} | {:error, term()}
  def execute(command_name, opts \\ []) do
    args = if is_list(opts), do: Keyword.get(opts, :args, []), else: Map.get(opts, :args, [])

    context =
      if is_list(opts), do: Keyword.get(opts, :context, %{}) |> Enum.into(%{}), else: Map.get(opts, :context, %{})

    dispatch(command_name, args, context)
  end

  @doc """
  Returns command definitions for all registered commands.
  """
  @spec get_definitions() :: [map()]
  def get_definitions do
    list_commands()
    |> Enum.map(fn name ->
      case get_command(name) do
        {:ok, details} -> details
        {:error, _} -> nil
      end
    end)
    |> Enum.reject(&is_nil/1)
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    # Create ETS table for fast public reads
    :ets.new(@table, [
      :set,
      :named_table,
      :public,
      read_concurrency: true
    ])

    {:ok, %{aliases: %{}, stats: %{dispatches: 0, errors: 0}}}
  end

  @impl true
  def handle_call({:register, command_module}, _from, state) do
    case validate_and_register(command_module, state) do
      {:ok, reply, new_state} -> {:reply, reply, new_state}
      {:error, reply} -> {:reply, reply, state}
    end
  end

  @impl true
  def handle_call({:dispatch, command_name, args, context}, _from, state) do
    {module, resolved_name} = resolve_command(command_name)

    if module == nil do
      new_stats = %{state.stats | errors: state.stats.errors + 1}
      {:reply, {:error, :unknown_command}, %{state | stats: new_stats}}
    else
      execute_command(module, resolved_name, args, context, state)
    end
  end

  @impl true
  def handle_call(:get_stats, _from, state) do
    stats = %{
      commands_registered: :ets.info(@table, :size),
      dispatches: state.stats.dispatches,
      errors: state.stats.errors
    }

    {:reply, stats, state}
  end

  # Private Functions

  defp validate_and_register(command_module, state) do
    if behaviour_implemented?(command_module) do
      command_name = command_module.name()

      if String.starts_with?(command_name, "/") do
        register_command(command_name, command_module, state)
      else
        {:error, {:error, :invalid_name}}
      end
    else
      {:error, {:error, :invalid_behaviour}}
    end
  end

  defp register_command(command_name, command_module, state) do
    if :ets.member(@table, command_name) do
      {:error, {:error, :already_registered}}
    else
      :ets.insert(@table, {
        command_name,
        %{
          module: command_module,
          description: command_module.description(),
          usage: command_module.usage()
        }
      })

      {:ok, :ok, state}
    end
  end

  defp resolve_command(command_name) do
    case :ets.lookup(@table, command_name) do
      [{^command_name, info}] ->
        {info.module, command_name}

      [] ->
        resolve_fuzzy(command_name)
    end
  end

  defp resolve_fuzzy(command_name) do
    all_commands = :ets.select(@table, [{{:"$1", :_}, [], [:"$1"]}])

    case find_closest_match(command_name, all_commands) do
      {:ok, matched_name} ->
        [{^matched_name, info}] = :ets.lookup(@table, matched_name)
        {info.module, matched_name}

      :error ->
        {nil, command_name}
    end
  end

  defp execute_command(module, resolved_name, args, context, state) do
    result = module.execute(args, context)
    new_dispatches = state.stats.dispatches + 1
    new_stats = %{state.stats | dispatches: new_dispatches}
    {:reply, result, %{state | stats: new_stats}}
  rescue
    error ->
      Logger.error("Command execution error for #{resolved_name}: #{inspect(error)}")
      new_stats = %{state.stats | errors: state.stats.errors + 1}
      {:reply, {:error, :execution_failed}, %{state | stats: new_stats}}
  end

  defp behaviour_implemented?(module) do
    Code.ensure_loaded?(module) and
      function_exported?(module, :name, 0) and
      function_exported?(module, :description, 0) and
      function_exported?(module, :usage, 0) and
      function_exported?(module, :execute, 2)
  end

  defp find_closest_match(name, candidates) do
    # Find candidates with Levenshtein distance <= 2
    matches =
      Enum.filter(candidates, fn candidate ->
        levenshtein_distance(name, candidate) <= @max_levenshtein_distance
      end)

    case matches do
      [] ->
        :error

      [single] ->
        {:ok, single}

      multiple ->
        # Return the one with smallest distance
        best =
          Enum.min_by(multiple, fn candidate ->
            levenshtein_distance(name, candidate)
          end)

        {:ok, best}
    end
  end

  defp levenshtein_distance(s1, s2) do
    s1 = String.downcase(s1)
    s2 = String.downcase(s2)

    len1 = String.length(s1)
    len2 = String.length(s2)

    cond do
      len1 == 0 -> len2
      len2 == 0 -> len1
      true -> calculate_distance(s1, s2, len1, len2)
    end
  end

  defp calculate_distance(s1, s2, _len1, len2) do
    s1_chars = String.graphemes(s1)
    s2_chars = :erlang.list_to_tuple(String.graphemes(s2))

    # Initial row: [0, 1, 2, ..., len2]
    prev_row = :erlang.list_to_tuple(Enum.to_list(0..len2))

    final_row =
      Enum.reduce(Enum.with_index(s1_chars, 1), prev_row, fn {c1, i}, prev ->
        build_distance_row(c1, i, prev, s2_chars, len2)
      end)

    elem(final_row, len2)
  end

  defp build_distance_row(c1, i, prev_row, s2_chars, len2) do
    first_cell = i

    {row_list, _} =
      Enum.reduce(1..len2, {[first_cell], first_cell}, fn j, {acc, prev_val} ->
        c2 = elem(s2_chars, j - 1)
        cost = if c1 == c2, do: 0, else: 1

        deletion = elem(prev_row, j) + 1
        insertion = prev_val + 1
        substitution = elem(prev_row, j - 1) + cost

        val = min(deletion, min(insertion, substitution))
        {acc ++ [val], val}
      end)

    :erlang.list_to_tuple(row_list)
  end
end
