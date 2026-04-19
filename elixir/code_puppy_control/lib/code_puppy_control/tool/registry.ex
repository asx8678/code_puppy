defmodule CodePuppyControl.Tool.Registry do
  @moduledoc """
  ETS-backed registry for tool modules (bd-149).

  Each tool module implements the `CodePuppyControl.Tool` behaviour.
  The registry maps tool names (atoms) to their implementing modules.
  """

  use GenServer

  @table :tool_registry

  def start_link(_opts \\ []) do
    GenServer.start_link(__MODULE__, [], name: __MODULE__)
  end

  @doc "Register a tool module by its `name/0` callback."
  @spec register(module()) :: :ok | {:error, String.t()}
  def register(module) when is_atom(module) do
    case module.name() do
      name when is_atom(name) ->
        :ets.insert(@table, {name, module})
        :ok

      _ ->
        {:error, "invalid name from #{inspect(module)}"}
    end
  rescue
    e -> {:error, Exception.message(e)}
  end

  @doc "Look up a tool module by name."
  @spec lookup(atom()) :: {:ok, module()} | {:error, :not_found}
  def lookup(name) when is_atom(name) do
    case :ets.lookup(@table, name) do
      [{^name, module}] -> {:ok, module}
      [] -> {:error, :not_found}
    end
  end

  @doc "List all registered tools as `{name, module}` tuples."
  @spec list_all() :: [{atom(), module()}]
  def list_all do
    :ets.tab2list(@table)
  end

  # --- GenServer callbacks ---

  @impl true
  def init(_) do
    table = :ets.new(@table, [:set, :named_table, :public, read_concurrency: true])
    {:ok, %{table: table}}
  end

  @impl true
  def terminate(_reason, _state) do
    try do
      :ets.delete(@table)
    rescue
      _ -> :ok
    end

    :ok
  end
end
