defmodule Mana.Scheduler.Job do
  @moduledoc """
  Job definition struct for the Mana scheduler.

  Represents a recurring background job that can be scheduled using
  cron expressions or interval notation.

  ## Schedule formats

    * **Cron**: Standard 5-field expression `"*/30 * * * *"` (minute hour day month weekday)
    * **Interval**: Shorthand like `"30m"`, `"1h"`, `"6h"`, `"2d"`, `"45s"`

  ## Examples

      %Mana.Scheduler.Job{
        name: "daily-review",
        schedule: "0 9 * * *",
        agent: "code-puppy",
        prompt: "Review all open pull requests",
        enabled: true
      }

      %Mana.Scheduler.Job{
        name: "health-check",
        schedule: "30m",
        agent: "watchdog",
        prompt: "Check system health",
        enabled: true
      }
  """

  @type schedule :: String.t()
  @type status :: nil | :success | :failed | :running

  @type t :: %__MODULE__{
          id: String.t(),
          name: String.t(),
          schedule: schedule(),
          agent: String.t(),
          prompt: String.t(),
          model: String.t(),
          working_directory: String.t(),
          enabled: boolean(),
          last_run: DateTime.t() | nil,
          last_status: status(),
          last_exit_code: integer() | nil,
          created_at: DateTime.t()
        }

  @enforce_keys [:name, :schedule, :agent, :prompt]
  defstruct [
    :id,
    :name,
    :schedule,
    :agent,
    :prompt,
    model: "",
    working_directory: ".",
    enabled: true,
    last_run: nil,
    last_status: nil,
    last_exit_code: nil,
    created_at: nil
  ]

  @doc """
  Creates a new job with generated ID and timestamps.
  """
  @spec new(keyword()) :: t()
  def new(attrs) when is_list(attrs) do
    attrs
    |> Enum.into(%{})
    |> new()
  end

  @spec new(map()) :: t()
  def new(attrs) when is_map(attrs) do
    now = DateTime.utc_now()

    struct!(__MODULE__, attrs)
    |> Map.put(:id, Map.get(attrs, :id, generate_id()))
    |> Map.put(:created_at, Map.get(attrs, :created_at, now))
  end

  @doc """
  Converts a job to a JSON-compatible map.

  DateTime fields are serialized as ISO8601 strings for persistence.
  """
  @spec to_map(t()) :: map()
  def to_map(%__MODULE__{} = job) do
    %{
      "id" => job.id,
      "name" => job.name,
      "schedule" => job.schedule,
      "agent" => job.agent,
      "prompt" => job.prompt,
      "model" => job.model,
      "working_directory" => job.working_directory,
      "enabled" => job.enabled,
      "last_run" => serialize_datetime(job.last_run),
      "last_status" => job.last_status,
      "last_exit_code" => job.last_exit_code,
      "created_at" => serialize_datetime(job.created_at)
    }
  end

  @doc """
  Builds a job from a JSON-decoded map (e.g., loaded from disk).

  Parses ISO8601 strings back into DateTime structs.
  """
  @spec from_map(map()) :: t()
  def from_map(data) when is_map(data) do
    %__MODULE__{
      id: data["id"],
      name: data["name"],
      schedule: data["schedule"],
      agent: data["agent"],
      prompt: data["prompt"],
      model: data["model"] || "",
      working_directory: data["working_directory"] || ".",
      enabled: data["enabled"] != false,
      last_run: parse_datetime(data["last_run"]),
      last_status: parse_status(data["last_status"]),
      last_exit_code: data["last_exit_code"],
      created_at: parse_datetime(data["created_at"])
    }
  end

  # ---------------------------------------------------------------------------
  # Private helpers
  # ---------------------------------------------------------------------------

  defp generate_id do
    :crypto.strong_rand_bytes(4) |> Base.encode16(case: :lower)
  end

  defp serialize_datetime(nil), do: nil
  defp serialize_datetime(%DateTime{} = dt), do: DateTime.to_iso8601(dt)

  defp parse_datetime(nil), do: nil

  defp parse_datetime(str) when is_binary(str) do
    case DateTime.from_iso8601(str) do
      {:ok, dt, _offset} -> dt
      {:error, _} -> nil
    end
  end

  defp parse_datetime(_), do: nil

  defp parse_status(nil), do: nil
  defp parse_status("success"), do: :success
  defp parse_status("failed"), do: :failed
  defp parse_status("running"), do: :running
  defp parse_status(s) when is_atom(s), do: s
  defp parse_status(_), do: nil
end
