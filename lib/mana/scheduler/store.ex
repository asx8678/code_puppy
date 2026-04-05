defmodule Mana.Scheduler.Store do
  @moduledoc """
  JSON file persistence for scheduled jobs.

  Stores jobs in `~/.mana/scheduler/jobs.json` using atomic writes
  (write to temp file, then rename) to prevent corruption.

  ## Compatibility

  The JSON format is designed to be compatible with the Python scheduler's
  `scheduled_tasks.json` format where possible, sharing fields like
  `name`, `agent`, `prompt`, `enabled`, `last_run`, etc.

  ## Usage

      # Store a new job
      job = Mana.Scheduler.Job.new(name: "test", schedule: "1h", agent: "code-puppy", prompt: "Hello")
      {:ok, job} = Mana.Scheduler.Store.put(job)

      # List all jobs
      {:ok, jobs} = Mana.Scheduler.Store.list()

      # Get a specific job
      {:ok, job} = Mana.Scheduler.Store.get("abc123")

      # Delete a job
      :ok = Mana.Scheduler.Store.delete("abc123")
  """

  alias Mana.Config.Paths
  alias Mana.Scheduler.Job

  @jobs_dir "scheduler"
  @jobs_file "jobs.json"

  # ---------------------------------------------------------------------------
  # Public API
  # ---------------------------------------------------------------------------

  @doc """
  Returns the path to the scheduler directory.
  """
  @spec scheduler_dir() :: String.t()
  def scheduler_dir do
    Path.join(Paths.data_dir(), @jobs_dir)
  end

  @doc """
  Returns the path to the jobs JSON file.
  """
  @spec jobs_file() :: String.t()
  def jobs_file do
    Path.join(scheduler_dir(), @jobs_file)
  end

  @doc """
  Lists all stored jobs.

  Returns `{:ok, [%Job{}]}` on success, `{:error, reason}` on failure.
  """
  @spec list() :: {:ok, [Job.t()]} | {:error, term()}
  def list do
    case read_jobs_file() do
      {:ok, data} ->
        jobs = Enum.map(data, &Job.from_map/1)
        {:ok, jobs}

      {:error, :enoent} ->
        {:ok, []}

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Gets a single job by its ID.

  Returns `{:ok, %Job{}}` if found, `{:error, :not_found}` otherwise.
  """
  @spec get(String.t()) :: {:ok, Job.t()} | {:error, :not_found | term()}
  def get(id) when is_binary(id) do
    case list() do
      {:ok, jobs} ->
        case Enum.find(jobs, fn job -> job.id == id end) do
          nil -> {:error, :not_found}
          job -> {:ok, job}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Puts a job into the store.

  If a job with the same ID already exists, it is replaced.
  If the job has no ID, one is generated.

  Returns `{:ok, %Job{}}` with the stored job on success.
  """
  @spec put(Job.t()) :: {:ok, Job.t()} | {:error, term()}
  def put(%Job{} = job) do
    job = ensure_id(job)

    case list() do
      {:ok, jobs} ->
        # Replace existing or append new
        updated =
          jobs
          |> Enum.reject(fn j -> j.id == job.id end)
          |> Kernel.++([job])

        case write_jobs_file(Enum.map(updated, &Job.to_map/1)) do
          :ok -> {:ok, job}
          {:error, reason} -> {:error, reason}
        end

      {:error, :enoent} ->
        # First job ever
        case write_jobs_file([Job.to_map(job)]) do
          :ok -> {:ok, job}
          {:error, reason} -> {:error, reason}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Deletes a job by ID.

  Returns `:ok` if the job was found and deleted,
  `{:error, :not_found}` if no such job exists.
  """
  @spec delete(String.t()) :: :ok | {:error, :not_found | term()}
  def delete(id) when is_binary(id) do
    case list() do
      {:ok, jobs} ->
        remaining = Enum.reject(jobs, fn job -> job.id == id end)

        if length(remaining) == length(jobs) do
          {:error, :not_found}
        else
          case write_jobs_file(Enum.map(remaining, &Job.to_map/1)) do
            :ok -> :ok
            {:error, reason} -> {:error, reason}
          end
        end

      {:error, :enoent} ->
        {:error, :not_found}

      {:error, reason} ->
        {:error, reason}
    end
  end

  # ---------------------------------------------------------------------------
  # Private helpers
  # ---------------------------------------------------------------------------

  defp ensure_id(%Job{id: nil} = job), do: %{job | id: generate_id()}
  defp ensure_id(%Job{id: ""} = job), do: %{job | id: generate_id()}
  defp ensure_id(%Job{} = job), do: job

  defp generate_id do
    :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)
  end

  defp ensure_scheduler_dir do
    File.mkdir_p(scheduler_dir())
  end

  defp read_jobs_file do
    path = jobs_file()

    with {:ok, contents} <- File.read(path),
         {:ok, data} <- Jason.decode(contents) do
      {:ok, data}
    end
  end

  defp write_jobs_file(data) do
    ensure_scheduler_dir()
    path = jobs_file()

    case Jason.encode(data, pretty: true) do
      {:ok, json} ->
        # Atomic write: write to temp file, then rename
        tmp_path = path <> ".tmp"

        with :ok <- File.write(tmp_path, json) do
          case File.rename(tmp_path, path) do
            :ok ->
              :ok

            {:error, reason} ->
              # Clean up temp file on rename failure
              File.rm(tmp_path)
              {:error, reason}
          end
        end

      {:error, reason} ->
        {:error, reason}
    end
  end
end
