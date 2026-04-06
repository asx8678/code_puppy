defmodule Mana.Tools.SchedulerTools do
  @moduledoc """
  Scheduler tools for agent access to scheduled task management.

  Provides two tools:
  - `scheduler_list_tasks` — query all scheduled tasks
  - `scheduler_create_task` — create a new scheduled task

  These tools allow agents to inspect and create scheduled jobs
  programmatically during conversations.

  ## Usage

      Mana.Tools.SchedulerTools.ListTasks.execute(%{})
      # => {:ok, %{\"tasks\" => [...], \"count\" => 3}}

      Mana.Tools.SchedulerTools.CreateTask.execute(%{
        \"name\" => \"daily-review\",
        \"schedule\" => \"0 9 * * *\",
        \"agent\" => \"assistant\",
        \"prompt\" => \"Review all open pull requests\"
      })
  """

  alias Mana.Scheduler.{Job, Store}

  defmodule ListTasks do
    @moduledoc "Tool to list all scheduled tasks"
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "scheduler_list_tasks"

    @impl true
    def description do
      "List all scheduled background tasks. Returns each task's name, schedule, agent, prompt, enabled status, and last run info."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          include_disabled: %{
            type: "boolean",
            description: "Whether to include disabled tasks (default: true)"
          }
        },
        required: []
      }
    end

    @impl true
    def execute(args) do
      include_disabled = Map.get(args, "include_disabled", true)

      case Store.list() do
        {:ok, jobs} ->
          filtered =
            if include_disabled do
              jobs
            else
              Enum.filter(jobs, & &1.enabled)
            end

          task_data =
            Enum.map(filtered, fn job ->
              %{
                "id" => job.id,
                "name" => job.name,
                "schedule" => job.schedule,
                "agent" => job.agent,
                "prompt" => job.prompt,
                "model" => job.model,
                "enabled" => job.enabled,
                "last_run" => job.last_run && DateTime.to_iso8601(job.last_run),
                "last_status" => job.last_status && Atom.to_string(job.last_status),
                "created_at" => job.created_at && DateTime.to_iso8601(job.created_at)
              }
            end)

          {:ok, %{"tasks" => task_data, "count" => length(task_data)}}

        {:error, reason} ->
          {:error, "Failed to list tasks: #{inspect(reason)}"}
      end
    end
  end

  defmodule CreateTask do
    @moduledoc "Tool to create a new scheduled task"
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "scheduler_create_task"

    @impl true
    def description do
      "Create a new scheduled background task. The task will run automatically according to its schedule expression."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          name: %{
            type: "string",
            description: "Unique name for the task (e.g., 'daily-review')"
          },
          schedule: %{
            type: "string",
            description: "Cron expression (e.g., '*/30 * * * *') or interval shorthand (e.g., '30m', '1h', '6h')"
          },
          agent: %{
            type: "string",
            description: "Name of the agent to run (e.g., 'assistant')"
          },
          prompt: %{
            type: "string",
            description: "The prompt/instruction to send to the agent when the task fires"
          },
          model: %{
            type: "string",
            description: "Optional model name override for the agent run"
          },
          working_directory: %{
            type: "string",
            description: "Optional working directory for the task (default: '.')"
          }
        },
        required: ["name", "schedule", "agent", "prompt"]
      }
    end

    @impl true
    def execute(%{"name" => name, "schedule" => schedule, "agent" => agent, "prompt" => prompt} = args) do
      # Check for duplicate name
      case find_job_by_name(name) do
        {:ok, _existing} ->
          {:error, "Task '#{name}' already exists. Use a different name."}

        :not_found ->
          model = Map.get(args, "model", "")
          work_dir = Map.get(args, "working_directory", ".")

          job =
            Job.new(%{
              name: name,
              schedule: schedule,
              agent: agent,
              prompt: prompt,
              model: model,
              working_directory: work_dir
            })

          case Store.put(job) do
            {:ok, stored_job} ->
              {:ok,
               %{
                 "created" => true,
                 "id" => stored_job.id,
                 "name" => stored_job.name,
                 "schedule" => stored_job.schedule,
                 "agent" => stored_job.agent,
                 "next_run" => next_run_description(stored_job)
               }}

            {:error, reason} ->
              {:error, "Failed to create task: #{inspect(reason)}"}
          end
      end
    end

    def execute(_args) do
      {:error, "Missing required parameters: name, schedule, agent, prompt"}
    end

    defp find_job_by_name(name) do
      case Store.list() do
        {:ok, jobs} ->
          case Enum.find(jobs, fn job -> job.name == name end) do
            nil -> :not_found
            job -> {:ok, job}
          end

        {:error, _} ->
          :not_found
      end
    end

    defp next_run_description(job) do
      now = DateTime.utc_now()

      case Mana.Scheduler.Cron.next_run(job.schedule, job.last_run, now) do
        {:ok, next_dt} -> DateTime.to_iso8601(next_dt)
        {:error, _} -> "unknown"
      end
    end
  end
end
