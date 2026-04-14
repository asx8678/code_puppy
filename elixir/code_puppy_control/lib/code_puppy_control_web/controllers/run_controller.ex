defmodule CodePuppyControlWeb.RunController do
  @moduledoc """
  Controller for run management API endpoints.
  """

  use CodePuppyControlWeb, :controller

  require Logger

  alias CodePuppyControl.Run.{State, Supervisor}
  alias CodePuppyControl.PythonWorker.Supervisor, as: WorkerSupervisor

  @doc """
  POST /api/runs

  Creates a new run with an associated Python worker.
  """
  def create(conn, params) do
    run_id = generate_run_id()
    metadata = Map.get(params, "metadata", %{})

    Logger.info("Creating new run #{run_id}")

    # Start the run state process
    with {:ok, _pid} <- Supervisor.start_run(run_id, metadata),
         # Start the Python worker for this run
         {:ok, _worker_pid} <- WorkerSupervisor.start_worker(run_id, metadata: metadata) do
      # Update status to running
      State.set_status(run_id, :running)

      conn
      |> put_status(:created)
      |> json(%{
        "id" => run_id,
        "status" => "running",
        "created_at" => DateTime.utc_now() |> DateTime.to_iso8601()
      })
    else
      {:error, reason} ->
        Logger.error("Failed to create run #{run_id}: #{inspect(reason)}")

        conn
        |> put_status(:internal_server_error)
        |> json(%{"error" => "Failed to create run", "details" => inspect(reason)})
    end
  end

  @doc """
  GET /api/runs/:id

  Gets the current status of a run.
  """
  def show(conn, %{"id" => run_id}) do
    case State.get_state(run_id) do
      {:ok, state} ->
        json(conn, %{
          "id" => run_id,
          "status" => state.status,
          "started_at" => format_datetime(state.started_at),
          "completed_at" => format_datetime(state.completed_at),
          "error" => state.error,
          "metadata" => state.metadata
        })

      {:error, :not_found} ->
        conn
        |> put_status(:not_found)
        |> json(%{"error" => "Run not found"})
    end
  end

  @doc """
  DELETE /api/runs/:id

  Stops and cleans up a run.
  """
  def delete(conn, %{"id" => run_id}) do
    Logger.info("Deleting run #{run_id}")

    # Stop the Python worker first
    WorkerSupervisor.terminate_worker(run_id)

    # Then stop the run state process
    Supervisor.terminate_run(run_id)

    send_resp(conn, :no_content, "")
  end

  @doc """
  POST /api/runs/:id/execute

  Executes a tool via the Python worker.
  """
  def execute(conn, %{"id" => run_id} = params) do
    tool_name = Map.get(params, "tool_name") || Map.get(params, "tool")
    arguments = Map.get(params, "arguments") || Map.get(params, "args", %{})

    if is_nil(tool_name) do
      conn
      |> put_status(:bad_request)
      |> json(%{"error" => "Missing required field: tool_name"})
    else
      alias CodePuppyControl.PythonWorker.Port

      # Record the request
      State.record_request(run_id, %{
        "tool_name" => tool_name,
        "arguments" => arguments
      })

      # Execute via Python worker
      case Port.call(run_id, "tools/call", %{
             "name" => tool_name,
             "arguments" => arguments
           }) do
        {:ok, result} ->
          State.record_response(run_id, result)

          conn
          |> put_status(:ok)
          |> json(%{
            "run_id" => run_id,
            "tool_name" => tool_name,
            "result" => result,
            "executed_at" => DateTime.utc_now() |> DateTime.to_iso8601()
          })

        {:error, reason} ->
          State.record_response(run_id, %{"error" => reason})

          conn
          |> put_status(:internal_server_error)
          |> json(%{
            "run_id" => run_id,
            "tool_name" => tool_name,
            "error" => inspect(reason)
          })
      end
    end
  end

  @doc """
  GET /api/runs/:id/history

  Gets the request/response history for a run.
  """
  def history(conn, %{"id" => run_id}) do
    case State.get_history(run_id) do
      [] ->
        conn
        |> put_status(:not_found)
        |> json(%{"error" => "Run not found or no history"})

      history ->
        json(conn, %{
          "run_id" => run_id,
          "history" => Enum.reverse(history)
        })
    end
  end

  # Private functions

  defp generate_run_id do
    base = System.unique_integer([:positive])
    timestamp = System.system_time(:millisecond)
    "run-#{timestamp}-#{base}"
  end

  defp format_datetime(nil), do: nil

  defp format_datetime(dt) do
    DateTime.to_iso8601(dt)
  end
end
