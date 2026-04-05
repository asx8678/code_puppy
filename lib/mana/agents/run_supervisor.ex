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
  alias Mana.Agents.Registry, as: AgentsRegistry
  alias Mana.Agent.Server, as: AgentServer

  @type run_spec :: {String.t(), String.t(), keyword()}
  @type run_result :: {String.t(), {:ok, String.t()} | {:error, term()}}

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
  Start multiple agent runs in parallel, collecting results.

  Each run is resolved by agent name via the `Mana.Agents.Registry`,
  started as a supervised task under this `DynamicSupervisor`, and
  awaited for its result. Concurrency is limited by `:max_parallel`.

  ## Parameters

    - `runs` - List of `{agent_name, message, run_opts}` tuples where
      `agent_name` is a string matching a registered agent name.
    - `opts` - Keyword list of options:
      - `:max_parallel` - Maximum number of concurrent runs (default: 4)
      - `:supervisor` - The supervisor to start the children under (default: `RunSupervisor`)
      - `:timeout` - Per-run timeout in milliseconds (default: 120_000)

  ## Returns

    - `{:ok, [{agent_name, result}]}` - Results from all runs, in order
    - `{:error, term()}` - A fatal error occurred (e.g., agent not found)

  ## Examples

      runs = [
        {"coder", "Write a function", []},
        {"reviewer", "Review this code", [timeout: 5000]}
      ]
      {:ok, results} = RunSupervisor.start_parallel_runs(runs, max_parallel: 2)
      # results => [{"coder", {:ok, "..."}}, {"reviewer", {:ok, "..."}}]

  """
  @spec start_parallel_runs([run_spec()], keyword()) ::
          {:ok, [run_result()]} | {:error, term()}
  def start_parallel_runs(runs, opts \\ []) when is_list(runs) do
    max_parallel = Keyword.get(opts, :max_parallel, 4)
    supervisor = Keyword.get(opts, :supervisor, __MODULE__)
    run_timeout = Keyword.get(opts, :timeout, 120_000)

    if runs == [] do
      {:ok, []}
    else
      do_parallel_runs(runs, supervisor, max_parallel, run_timeout)
    end
  end

  # ------------------------------------------------------------------
  # Private helpers for start_parallel_runs/2
  # ------------------------------------------------------------------

  defp do_parallel_runs(runs, supervisor, max_parallel, run_timeout) do
    results =
      runs
      |> Task.async_stream(
        fn {agent_name, message, run_opts} ->
          execute_named_run(agent_name, message, run_opts, supervisor, run_timeout)
        end,
        max_concurrency: max_parallel,
        ordered: true,
        timeout: :infinity
      )
      |> Enum.map(fn
        {:ok, result} -> result
        {:exit, reason} -> {:error, reason}
      end)

    case Enum.find(results, &match?({:error, {:agent_not_found, _}}, &1)) do
      nil -> {:ok, results}
      error -> error
    end
  end

  # Resolve the agent def from the registry, start a supervised task,
  # and collect the result.
  defp execute_named_run(agent_name, message, run_opts, supervisor, run_timeout) do
    case resolve_agent(agent_name) do
      {:ok, agent_def} ->
        result =
          run_agent_supervised(
            agent_name,
            agent_def,
            message,
            run_opts,
            supervisor,
            run_timeout
          )

        {agent_name, result}

      {:error, reason} ->
        {:error, {:agent_not_found, reason}}
    end
  end

  defp resolve_agent(agent_name) do
    case AgentsRegistry.get_agent(agent_name) do
      nil -> {:error, "Agent not found: #{agent_name}"}
      agent_def -> {:ok, agent_def}
    end
  end

  # Start a supervised task that runs the agent and sends the result
  # back to the caller before exiting.
  defp run_agent_supervised(
         agent_name,
         agent_def,
         message,
         run_opts,
         supervisor,
         run_timeout
       ) do
    {:ok, agent_pid} =
      AgentServer.start_link(agent_def: normalize_agent_def(agent_def))

    caller = self()
    merged_opts = Keyword.put(run_opts, :supervisor, supervisor)

    task_spec = %{
      id: make_ref(),
      start:
        {Task, :start_link,
         [
           fn ->
             Logger.debug("Starting parallel run for agent #{agent_name}")

             result =
               try do
                 Runner.run(agent_pid, message, merged_opts)
               rescue
                 e -> {:error, Exception.message(e)}
               after
                 if Process.alive?(agent_pid),
                   do: GenServer.stop(agent_pid, :normal, 5_000)
               end

             Logger.debug("Parallel run for agent #{agent_name} completed")

             # Send result back to caller before exiting
             send(caller, {ref = make_ref(), result})
             ref
           end
         ]},
      restart: :temporary
    }

    case DynamicSupervisor.start_child(supervisor, task_spec) do
      {:ok, task_pid} ->
        await_task_result(task_pid, run_timeout)

      {:error, reason} ->
        if Process.alive?(agent_pid),
          do: GenServer.stop(agent_pid, :normal, 5_000)

        {:error, reason}
    end
  end

  # Wait for the supervised task to send its result, with a timeout.
  defp await_task_result(task_pid, timeout) do
    ref = Process.monitor(task_pid)
    result_key = make_ref()

    # The task sends {^result_key, result} — but we don't know the ref
    # the task will use, so we monitor and receive.
    receive do
      {_task_ref, {:ok, _} = result} when is_reference(elem(_task_ref, 0)) ->
        Process.demonitor(ref, [:flush])
        result

      {_task_ref, {:error, _} = result} ->
        Process.demonitor(ref, [:flush])
        result

      {:DOWN, ^ref, :process, ^task_pid, :normal} ->
        # Task exited — drain any late result message
        receive do
          {_ref, result} -> result
        after
          0 -> {:ok, :completed}
        end

      {:DOWN, ^ref, :process, ^task_pid, reason} ->
        Process.demonitor(ref, [:flush])
        {:error, reason}
    after
      timeout ->
        Process.demonitor(ref, [:flush])
        Process.exit(task_pid, :kill)
        {:error, :timeout}
    end
  end

  defp normalize_agent_def(agent_def) when is_map(agent_def) do
    agent_def
    |> Enum.map(fn
      {"name", v} -> {:name, v}
      {"display_name", v} -> {:display_name, v}
      {"description", v} -> {:description, v}
      {"system_prompt", v} -> {:system_prompt, v}
      {"available_tools", v} -> {:available_tools, v}
      {"user_prompt", v} -> {:user_prompt, v}
      {"tools_config", v} -> {:tools_config, v}
      {k, v} -> {k, v}
    end)
    |> Map.new()
  end
end
