defmodule CodePuppyControl.Run.Manager do
  @moduledoc """
  Coordinates run lifecycle between Registry, State, and Workers.

  This is the high-level API for managing runs:
  - Starting runs with associated Python workers
  - Tracking run state and progress
  - Cancelling and cleaning up runs
  - Querying run information

  ## Usage

      {:ok, run_id} = Run.Manager.start_run("session-123", "elixir-dev", config: %{})
      Run.Manager.get_run(run_id)
      Run.Manager.cancel_run(run_id)
  """

  require Logger

  alias CodePuppyControl.{Run, PythonWorker}

  @doc """
  Starts a new run with an associated Python worker.

  ## Options

    * `:config` - Configuration map to pass to the Python worker
    * `:metadata` - Additional metadata for the run

  ## Returns

    * `{:ok, run_id}` - Run started successfully
    * `{:error, reason}` - Failed to start run

  ## Examples

      {:ok, run_id} = Run.Manager.start_run("session-123", "elixir-dev")
      {:ok, run_id} = Run.Manager.start_run("session-123", "elixir-dev", config: %{"model" => "claude"})
  """
  @spec start_run(String.t(), String.t(), keyword()) :: {:ok, String.t()} | {:error, term()}
  def start_run(session_id, agent_name, opts \\ []) do
    run_id = generate_run_id()
    config = Keyword.get(opts, :config, %{})
    metadata = Keyword.get(opts, :metadata, %{})

    # Note: Telemetry.run_start is emitted in Run.State.init for consistency
    # This ensures we track the actual process start time accurately

    Logger.info("Starting run #{run_id} for session #{session_id}, agent #{agent_name}")

    # Merge session and agent info into metadata
    full_metadata =
      metadata
      |> Map.put(:session_id, session_id)
      |> Map.put(:agent_name, agent_name)
      |> Map.put(:config, config)

    # Start Python worker first
    with {:ok, worker_pid} <- PythonWorker.Supervisor.start_worker(run_id),
         # Start run state tracker with link to worker
         {:ok, _state_pid} <-
           Run.Supervisor.start_run(run_id,
             session_id: session_id,
             agent_name: agent_name,
             worker_pid: worker_pid,
             metadata: full_metadata
           ) do
      # Tell worker to start the run
      # Use run_id for Registry lookup, not worker_pid
      PythonWorker.Port.start_run(run_id, %{
        run_id: run_id,
        session_id: session_id,
        agent_name: agent_name,
        config: config
      })

      Logger.info("Run #{run_id} started successfully with worker #{inspect(worker_pid)}")
      {:ok, run_id}
    else
      {:error, reason} = error ->
        Logger.error("Failed to start run #{run_id}: #{inspect(reason)}")

        # Cleanup any partial state
        cleanup_failed_start(run_id)

        error
    end
  end

  @doc """
  Gets the current state of a run.

  ## Returns

    * `{:ok, state}` - The run state
    * `{:error, :not_found}` - Run doesn't exist
  """
  @spec get_run(String.t()) :: {:ok, Run.State.t()} | {:error, :not_found}
  def get_run(run_id) do
    Run.State.get_state(run_id)
  end

  @doc """
  Cancels a running run.

  Sends a cancel signal to the Python worker and updates the run state.

  ## Returns

    * `:ok` - Cancel command sent
    * `{:error, :not_found}` - Run doesn't exist
  """
  @spec cancel_run(String.t(), term() | nil) :: :ok | {:error, :not_found}
  def cancel_run(run_id, reason \\ nil) do
    case get_run(run_id) do
      {:ok, %{status: status}} when status in [:completed, :failed, :cancelled] ->
        # Already finished, nothing to do
        :ok

      {:ok, _} ->
        # Send cancel to worker, update state
        PythonWorker.Port.cancel_run(run_id)
        Run.State.cancel(run_id, reason || "user_cancelled")
        :ok

      {:error, :not_found} ->
        {:error, :not_found}
    end
  end

  @doc """
  Lists all runs for a specific session.

  Returns a list of `{run_id, status}` tuples.
  """
  @spec list_runs(String.t() | nil) :: list({String.t(), atom()})
  def list_runs(session_id \\ nil) do
    # Get all active run state processes
    Run.Supervisor.list_runs()
    |> Enum.flat_map(fn {run_id, _pid} ->
      case get_run(run_id) do
        {:ok, state} ->
          if is_nil(session_id) or state.session_id == session_id do
            [{run_id, state.status}]
          else
            []
          end

        {:error, :not_found} ->
          []
      end
    end)
  end

  @doc """
  Lists all runs with full details for a session.
  """
  @spec list_runs_with_details(String.t() | nil) :: list(map())
  def list_runs_with_details(session_id \\ nil) do
    list_runs(session_id)
    |> Enum.flat_map(fn {run_id, _status} ->
      case get_run(run_id) do
        {:ok, state} ->
          [
            %{
              run_id: run_id,
              session_id: state.session_id,
              agent_name: state.agent_name,
              status: state.status,
              started_at: state.started_at,
              completed_at: state.completed_at,
              error: state.error,
              metadata: state.metadata
            }
          ]

        {:error, :not_found} ->
          []
      end
    end)
  end

  @doc """
  Waits for a run to complete.

  Returns when the run reaches a terminal state (:completed, :failed, :cancelled)
  or the timeout expires.

  ## Returns

    * `{:ok, state}` - Run completed
    * `{:timeout, state}` - Timeout reached
  """
  @spec await_run(String.t(), non_neg_integer()) ::
          {:ok, Run.State.t()} | {:timeout, Run.State.t()}
  def await_run(run_id, timeout_ms \\ 30_000) do
    start_time = System.monotonic_time(:millisecond)
    poll_interval = 100

    do_await_run(run_id, start_time, timeout_ms, poll_interval)
  end

  @doc """
  Deletes a run and cleans up associated resources.
  """
  @spec delete_run(String.t()) :: :ok | {:error, :not_found}
  def delete_run(run_id) do
    # Check if run exists first
    case get_run(run_id) do
      {:ok, _} ->
        # Stop the Python worker first
        PythonWorker.Supervisor.terminate_worker(run_id)

        # Then stop the run state process
        Run.Supervisor.terminate_run(run_id)

        :ok

      {:error, :not_found} ->
        {:error, :not_found}
    end
  end

  # Private functions

  defp generate_run_id do
    base = System.unique_integer([:positive])
    timestamp = System.system_time(:millisecond)
    "run-#{timestamp}-#{base}"
  end

  defp cleanup_failed_start(run_id) do
    # Try to terminate any partially started processes
    PythonWorker.Supervisor.terminate_worker(run_id)
    Run.Supervisor.terminate_run(run_id)
  catch
    _ -> :ok
  end

  defp do_await_run(run_id, start_time, timeout_ms, poll_interval) do
    case get_run(run_id) do
      {:ok, %{status: status} = state} when status in [:completed, :failed, :cancelled] ->
        {:ok, state}

      {:ok, state} ->
        elapsed = System.monotonic_time(:millisecond) - start_time

        if elapsed >= timeout_ms do
          {:timeout, state}
        else
          Process.sleep(poll_interval)
          do_await_run(run_id, start_time, timeout_ms, poll_interval)
        end

      {:error, :not_found} ->
        {:error, :not_found}
    end
  end
end
