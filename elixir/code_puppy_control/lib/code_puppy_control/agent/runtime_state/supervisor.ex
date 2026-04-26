defmodule CodePuppyControl.Agent.RuntimeState.Supervisor do
  @moduledoc """
  DynamicSupervisor for per-agent RuntimeState processes.

  Each agent gets its own RuntimeState GenServer, keyed by `agent_name`,
  managing per-agent caches, lifecycle hooks, and stats collection.

  ## Restart Strategy

  `:temporary` — Agent.RuntimeState processes are disposable. If one crashes,
  the next access will create a fresh one with default state. This is safe
  because durable state lives in storage (Layer B), not in the runtime.
  """

  use DynamicSupervisor

  require Logger

  alias CodePuppyControl.Agent.RuntimeState

  @doc """
  Starts the DynamicSupervisor.
  """
  def start_link(init_arg) do
    DynamicSupervisor.start_link(__MODULE__, init_arg, name: __MODULE__)
  end

  @doc """
  Starts a RuntimeState process for the given agent_name.

  Returns `{:ok, pid}` on success. If a process already exists for
  this agent, returns `{:ok, existing_pid}` (idempotent).
  """
  @spec start_runtime_state(String.t(), keyword()) :: {:ok, pid()} | {:error, term()}
  def start_runtime_state(agent_name, opts \\ []) do
    opts = Keyword.merge(opts, agent_name: agent_name)

    child_spec = %{
      id: {RuntimeState, agent_name},
      start: {RuntimeState, :start_link, [opts]},
      restart: :temporary
    }

    case DynamicSupervisor.start_child(__MODULE__, child_spec) do
      {:ok, pid} ->
        {:ok, pid}

      {:ok, pid, _info} ->
        {:ok, pid}

      {:error, {:already_started, pid}} ->
        {:ok, pid}

      {:error, :max_children} ->
        limit = CodePuppyControl.Runtime.Limits.max_agent_states()

        Logger.warning(
          "Agent.RuntimeState supervisor at capacity (limit: #{limit}). " <>
            "Refusing to start #{agent_name}."
        )

        :telemetry.execute(
          [:code_puppy, :supervisor, :full],
          %{count: 1},
          %{supervisor: :agent_runtime_state, agent_name: agent_name}
        )

        {:error, :max_children}

      {:error, reason} = error ->
        Logger.error("Failed to start Agent.RuntimeState for #{agent_name}: #{inspect(reason)}")

        error
    end
  end

  @doc """
  Terminates a RuntimeState process for the given agent_name.
  """
  @spec terminate_runtime_state(String.t()) :: :ok | {:error, :not_found}
  def terminate_runtime_state(agent_name) do
    case Registry.lookup(CodePuppyControl.Agent.RuntimeState.Registry, agent_name) do
      [] ->
        {:error, :not_found}

      [{pid, _value} | _] ->
        DynamicSupervisor.terminate_child(__MODULE__, pid)
    end
  end

  @doc """
  Lists all active RuntimeState processes with their agent names and PIDs.
  """
  @spec list_runtime_states() :: list({String.t(), pid()})
  def list_runtime_states do
    DynamicSupervisor.which_children(__MODULE__)
    |> Enum.flat_map(fn
      {:undefined, pid, :worker, [RuntimeState]} when is_pid(pid) ->
        case Registry.keys(CodePuppyControl.Agent.RuntimeState.Registry, pid) do
          [key] -> [{key, pid}]
          _ -> []
        end

      _ ->
        []
    end)
  end

  @doc """
  Returns the count of active RuntimeState processes.
  """
  @spec runtime_state_count() :: non_neg_integer()
  def runtime_state_count do
    case Process.whereis(__MODULE__) do
      nil -> 0
      _ -> DynamicSupervisor.count_children(__MODULE__).workers
    end
  end

  @impl true
  def init(_init_arg) do
    DynamicSupervisor.init(
      strategy: :one_for_one,
      max_restarts: 100,
      max_seconds: 60,
      max_children: CodePuppyControl.Runtime.Limits.max_agent_states()
    )
  end
end
