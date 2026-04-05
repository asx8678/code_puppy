defmodule Mana.Scheduler.Runner do
  @moduledoc """
  GenServer that periodically checks for due scheduled jobs and fires them.

  Uses `Process.send_after/3` with a configurable tick interval (default 60 seconds).
  On each tick, it loads all enabled jobs from the store, checks which are due
  using `Mana.Scheduler.Cron`, and starts agent runs for due jobs.

  ## Architecture

      ┌─────────────────────────────┐
      │  Mana.Scheduler.Runner      │
      │  (GenServer)                │
      │                             │
      │  Every 60s:                 │
      │   1. Load enabled jobs      │
      │   2. Check Cron.should_run? │
      │   3. Fire due jobs          │
      │   4. Update last_run        │
      └─────────────────────────────┘

  ## Starting

  Started by `Mana.Scheduler.Supervisor` as part of the application tree.

      # Manual start (for testing)
      {:ok, pid} = Mana.Scheduler.Runner.start_link([])

  ## Configuration

    * `:tick_interval` — tick interval in milliseconds (default: 60_000)
    * `:enabled` — whether the runner is active (default: true)
  """

  use GenServer

  require Logger

  alias Mana.Scheduler.{Cron, Job, Store}

  @default_tick_interval 60_000
  @tick_msg :tick

  # ---------------------------------------------------------------------------
  # Client API
  # ---------------------------------------------------------------------------

  @doc """
  Starts the Runner GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Returns the current state of the runner (for debugging).
  """
  @spec get_state() :: map()
  def get_state do
    GenServer.call(__MODULE__, :get_state)
  end

  @doc """
  Manually triggers a tick (useful for testing).
  """
  @spec force_tick() :: :ok
  def force_tick do
    GenServer.cast(__MODULE__, :force_tick)
  end

  @doc """
  Enables the scheduler runner.
  """
  @spec enable() :: :ok
  def enable do
    GenServer.call(__MODULE__, :enable)
  end

  @doc """
  Disables the scheduler runner (stops processing jobs until re-enabled).
  """
  @spec disable() :: :ok
  def disable do
    GenServer.call(__MODULE__, :disable)
  end

  # ---------------------------------------------------------------------------
  # GenServer callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init(opts) do
    tick_interval = Keyword.get(opts, :tick_interval, @default_tick_interval)
    enabled = Keyword.get(opts, :enabled, true)

    state = %{
      tick_interval: tick_interval,
      enabled: enabled,
      timer_ref: nil,
      runs_started: 0
    }

    # Schedule first tick
    state = schedule_tick(state)

    Logger.info("[Scheduler.Runner] Started (tick_interval=#{tick_interval}ms, enabled=#{enabled})")

    {:ok, state}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, state}
  end

  @impl true
  def handle_call(:enable, _from, state) do
    new_state = schedule_tick(%{state | enabled: true})
    {:reply, :ok, new_state}
  end

  @impl true
  def handle_call(:disable, _from, state) do
    new_state = cancel_tick(%{state | enabled: false})
    {:reply, :ok, new_state}
  end

  @impl true
  def handle_cast(:force_tick, state) do
    new_state = do_tick(state)
    {:noreply, new_state}
  end

  @impl true
  def handle_info(@tick_msg, %{enabled: true} = state) do
    new_state = state |> Map.put(:timer_ref, nil) |> do_tick() |> schedule_tick()
    {:noreply, new_state}
  end

  @impl true
  def handle_info(@tick_msg, %{enabled: false} = state) do
    {:noreply, %{state | timer_ref: nil}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("[Scheduler.Runner] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ---------------------------------------------------------------------------
  # Tick logic
  # ---------------------------------------------------------------------------

  defp do_tick(state) do
    now = DateTime.utc_now()

    case Store.list() do
      {:ok, jobs} ->
        due_jobs =
          jobs
          |> Enum.filter(&(&1.enabled and Cron.job_due?(&1, now)))

        if due_jobs != [] do
          Logger.info("[Scheduler.Runner] Found #{length(due_jobs)} due job(s)")

          Enum.each(due_jobs, fn job ->
            fire_job(job, now)
          end)

          %{state | runs_started: state.runs_started + length(due_jobs)}
        else
          state
        end

      {:error, reason} ->
        Logger.warning("[Scheduler.Runner] Failed to load jobs: #{inspect(reason)}")
        state
    end
  end

  defp fire_job(%Job{} = job, now) do
    Logger.info("[Scheduler.Runner] Firing job: #{job.name} (#{job.id})")

    # Update last_run and status before starting
    updated_job = %{job | last_run: now, last_status: :running}
    Store.put(updated_job)

    case start_agent_run(job) do
      {:ok, _pid} ->
        :ok

      {:error, reason} ->
        Logger.warning("[Scheduler.Runner] Failed to start agent run for #{job.name}: #{inspect(reason)}")

        # Mark as failed
        failed_job = %{updated_job | last_status: :failed, last_exit_code: -1}
        Store.put(failed_job)
    end
  end

  defp start_agent_run(%Job{} = job) do
    # Try to use the agents system if available
    case resolve_agent(job.agent) do
      {:ok, agent_def} ->
        alias Mana.Agent.Server, as: AgentServer
        alias Mana.Agents.RunSupervisor

        {:ok, agent_pid} = AgentServer.start_link(agent_def: agent_def)

        RunSupervisor.start_run(agent_pid, job.prompt, [])

      {:error, _reason} ->
        # Fallback: start a simple Task that logs the execution
        Logger.warning("[Scheduler.Runner] Agent '#{job.agent}' not found, using simple task for job '#{job.name}'")

        Task.start(fn ->
          Logger.info("[Scheduler.Runner] Executing job '#{job.name}': #{job.prompt}")
          # Mark job as success after simple execution
          case Store.get(job.id) do
            {:ok, stored_job} ->
              success_job = %{stored_job | last_status: :success, last_exit_code: 0}
              Store.put(success_job)

            _ ->
              :ok
          end
        end)
    end
  end

  defp resolve_agent(agent_name) do
    case Process.whereis(Mana.Agents.Registry) do
      nil ->
        {:error, :registry_not_started}

      _pid ->
        alias Mana.Agents.Registry, as: AgentsRegistry

        case AgentsRegistry.get_agent(agent_name) do
          nil -> {:error, :not_found}
          agent_def -> {:ok, normalize_agent_def(agent_def)}
        end
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

  # ---------------------------------------------------------------------------
  # Timer helpers
  # ---------------------------------------------------------------------------

  defp schedule_tick(%{tick_interval: interval} = state) do
    ref = Process.send_after(self(), @tick_msg, interval)
    %{state | timer_ref: ref}
  end

  defp cancel_tick(%{timer_ref: nil} = state), do: state

  defp cancel_tick(%{timer_ref: ref} = state) do
    Process.cancel_timer(ref)
    %{state | timer_ref: nil}
  end
end
