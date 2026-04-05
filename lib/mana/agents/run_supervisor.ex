defmodule Mana.Agents.RunSupervisor do
  @moduledoc """
  DynamicSupervisor for agent run Tasks.

  Manages supervised, temporary tasks for running agent operations.
  Each run is started as a separate supervised task that terminates
  when the run completes.

  ## Usage

      {:ok, _pid} = Mana.Agents.RunSupervisor.start_link()

      # Start an agent run
      {:ok, task_pid} = Mana.Agents.RunSupervisor.start_run(agent_pid, "Hello!")

  ## Supervision

  Tasks are started with `:temporary` restart policy, meaning they
  won't be restarted if they crash. This is appropriate for one-off
  agent runs where the user can simply retry if needed.

  """

  use DynamicSupervisor

  require Logger

  alias Mana.Agent.Runner

  @doc """
  Starts the RunSupervisor.

  ## Options

    - `:name` - The name to register the process under (default: `__MODULE__`)

  """
  @spec start_link(keyword()) :: DynamicSupervisor.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    DynamicSupervisor.start_link(__MODULE__, opts, name: name)
  end

  @impl true
  def init(opts) do
    max_children = Keyword.get(opts, :max_children, 50)

    DynamicSupervisor.init(
      strategy: :one_for_one,
      max_children: max_children
    )
  end

  @doc """
  Start an agent run as a supervised task.

  ## Parameters

    - `agent_pid` - PID of the agent server
    - `user_message` - The user message to process
    - `opts` - Keyword list of options passed to Runner.run/3
      - `:supervisor` - The supervisor to start the child under (default: `RunSupervisor`)

  ## Returns

    - `{:ok, pid}` - Task was started successfully
    - `{:error, :max_children}` - Maximum number of children reached
    - `{:error, term()}` - Failed to start task

  """
  @spec start_run(pid(), String.t(), keyword()) :: DynamicSupervisor.on_start_child()
  def start_run(agent_pid, user_message, opts \\ []) when is_pid(agent_pid) do
    supervisor = Keyword.get(opts, :supervisor, __MODULE__)
    _parent_supervisor = self()

    task_spec = %{
      id: make_ref(),
      start:
        {Task, :start_link,
         [
           fn ->
             Logger.debug("Starting agent run for agent #{inspect(agent_pid)}")

             try do
               case Runner.run(agent_pid, user_message, opts) do
                 {:ok, response} ->
                   Logger.debug("Agent run completed successfully")
                   {:ok, response}

                 {:error, reason} ->
                   Logger.warning("Agent run failed: #{inspect(reason)}")
                   {:error, reason}
               end
             after
               # Exit the task process when done
               exit(:normal)
             end
           end
         ]},
      restart: :temporary
    }

    DynamicSupervisor.start_child(supervisor, task_spec)
  end

  @doc """
  Start multiple agent runs in parallel as supervised tasks.

  ## Parameters

    - `runs` - List of `{agent_pid, user_message, run_opts}` tuples
    - `opts` - Keyword list of options:
      - `:max_parallel` - Maximum number of concurrent runs (default: 4)
      - `:supervisor` - The supervisor to start the children under (default: `RunSupervisor`)

  ## Returns

    - `{:ok, [pid]}` - All tasks were started successfully, returns list of task PIDs
    - `{:error, :max_children}` - Maximum number of children reached
    - `{:error, term()}` - Failed to start one or more tasks

  ## Examples

      runs = [
        {agent_pid1, "Hello", []},
        {agent_pid2, "World", [timeout: 5000]}
      ]
      {:ok, task_pids} = RunSupervisor.start_parallel_runs(runs, max_parallel: 2)

  """
  @spec start_parallel_runs(list({pid(), String.t(), keyword()}), keyword()) ::
          {:ok, list(pid())} | {:error, term()}
  def start_parallel_runs(runs, opts \\ []) when is_list(runs) do
    max_parallel = Keyword.get(opts, :max_parallel, 4)
    supervisor = Keyword.get(opts, :supervisor, __MODULE__)

    # Use Task.async_stream to respect max_parallel limit
    results =
      runs
      |> Task.async_stream(
        fn {agent_pid, user_message, run_opts} ->
          start_run(agent_pid, user_message, Keyword.put(run_opts, :supervisor, supervisor))
        end,
        max_concurrency: max_parallel,
        ordered: true,
        timeout: :infinity
      )
      |> Enum.map(fn
        {:ok, {:ok, pid}} -> {:ok, pid}
        {:ok, {:error, reason}} -> {:error, reason}
        {:exit, reason} -> {:error, reason}
      end)

    case Enum.split_with(results, &match?({:ok, _}, &1)) do
      {oks, []} ->
        {:ok, Enum.map(oks, fn {:ok, pid} -> pid end)}

      {_oks, errors} ->
        first_error = errors |> hd() |> elem(1)
        {:error, first_error}
    end
  end
end
