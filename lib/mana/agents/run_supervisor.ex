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
  def init(_opts) do
    DynamicSupervisor.init(
      strategy: :one_for_one,
      max_children: 50
    )
  end

  @doc """
  Start an agent run as a supervised task.

  ## Parameters

    - `agent_pid` - PID of the agent server
    - `user_message` - The user message to process
    - `opts` - Keyword list of options passed to Runner.run/3

  ## Returns

    - `{:ok, pid}` - Task was started successfully
    - `{:error, :max_children}` - Maximum number of children reached
    - `{:error, term()}` - Failed to start task

  """
  @spec start_run(pid(), String.t(), keyword()) :: DynamicSupervisor.on_start_child()
  def start_run(agent_pid, user_message, opts \\ []) when is_pid(agent_pid) do
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

    DynamicSupervisor.start_child(__MODULE__, task_spec)
  end
end
