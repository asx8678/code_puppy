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
    # Verify the module implements the behaviour
    if not behaviour_implemented?(command_module) do
      {:reply, {:error, :invalid_behaviour}, state}
    else
      command_name = command_module.name()

      # Validate command name starts with "/"
      if not String.starts_with?(command_name, "/") do
        {:reply, {:error, :invalid_name}, state}
      else
        # Check for duplicates
        if :ets.member(@table, command_name) do
          {:reply, {:error, :already_registered}, state}
        else
          # Store in ETS for public access
          :ets.insert(@table, {
            command_name,
            %{
              module: command_module,
              description: command_module.description(),
              usage: command_module.usage()
            }
          })

          {:reply, :ok, state}
        end
      end
    end
  end

  @impl true
  def handle_call({:dispatch, command_name, args, context}, _from, state) do
    # Try exact match first
    {module, resolved_name} =
      case :ets.lookup(@table, command_name) do
        [{^command_name, info}] ->
          {info.module, command_name}

        [] ->
          # Try fuzzy matching
          all_commands = :ets.select(@table, [{{:"$1", :_}, [], [:"$1"]}])

          case find_closest_match(command_name, all_commands) do
            {:ok, matched_name} ->
              [{^matched_name, info}] = :ets.lookup(@table, matched_name)
              {info.module, matched_name}

            :error ->
              {nil, command_name}
          end
      end

    if module == nil do
      new_stats = %{state.stats | errors: state.stats.errors + 1}
      {:reply, {:error, :unknown_command}, %{state | stats: new_stats}}
    else
      try do
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

    if len1 == 0 do
      len2
    else
      if len2 == 0 do
        len1
      else
        # Use dynamic programming approach
        prev_row = 0..len2 |> Enum.to_list()

        s1_chars = String.graphemes(s1)
        s2_chars = String.graphemes(s2)

        {distance, _} =
          Enum.reduce(s1_chars, {len2 + 1, prev_row}, fn c1, {_, prev} ->
            curr = [length(prev)]

            curr_row =
              Enum.reduce(1..len2, curr, fn j, acc ->
                cost = if c1 == Enum.at(s2_chars, j - 1), do: 0, else: 1

                deletion = Enum.at(prev, j) + 1
                insertion = List.last(acc) + 1
                substitution = Enum.at(prev, j - 1) + cost

                new_val = Enum.min([deletion, insertion, substitution])
                acc ++ [new_val]
              end)

            {List.last(curr_row), curr_row}
          end)

        distance
      end
    end
  end
end
