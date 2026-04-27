defmodule CodePuppyControl.Tools.CpSchedulerOps do
  @moduledoc """
  `:cp_`-prefixed Tool-behaviour wrappers for scheduler tools.

  These modules expose `CodePuppyControl.Tools.SchedulerTools` functions
  through the Tool behaviour so agents can call scheduler tools via
  the tool registry.

  The `:cp_` namespace distinguishes agent-facing tool names from
  internal tool module names, matching the naming convention used in
  `CodePuppyControl.Agents.CodePuppy.allowed_tools/0`.

  ## Architecture Note

  Unlike the Python scheduler which uses a daemon process with PID files,
  the Elixir scheduler runs as a supervised GenServer (`CronScheduler`).
  There is no `cp_scheduler_start_daemon` / `cp_scheduler_stop_daemon` —
  instead, `cp_scheduler_status` reports the always-on CronScheduler state
  and `cp_scheduler_force_check` triggers immediate schedule evaluation.

  ## Tools

  - `CpSchedulerListTasks` — List all tasks with status info
  - `CpSchedulerCreateTask` — Create a new scheduled task
  - `CpSchedulerDeleteTask` — Delete a task by ID or name
  - `CpSchedulerToggleTask` — Toggle a task's enabled/disabled state
  - `CpSchedulerStatus` — Check scheduler status
  - `CpSchedulerRunTask` — Run a task immediately
  - `CpSchedulerViewLog` — View execution history for a task
  - `CpSchedulerForceCheck` — Force immediate schedule evaluation

  Refs: code_puppy-mmk.2 (Phase E port)
  """

  alias CodePuppyControl.Tools.SchedulerTools

  defmodule CpSchedulerListTasks do
    @moduledoc "List all scheduled tasks with their status and scheduler info."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_list_tasks

    @impl true
    def description do
      "List all scheduled tasks with their status and daemon info. " <>
        "Returns a formatted overview of daemon status, all configured " <>
        "tasks with their schedules, and last run status for each task."
    end

    @impl true
    def parameters do
      %{"type" => "object", "properties" => %{}, "required" => []}
    end

    @impl true
    def invoke(_args, _context) do
      {:ok, %{output: SchedulerTools.list_tasks()}}
    end
  end

  defmodule CpSchedulerCreateTask do
    @moduledoc "Create a new scheduled task."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_create_task

    @impl true
    def description do
      "Create a new scheduled task. Creates a task that will run " <>
        "automatically according to the specified schedule. The scheduler " <>
        "must be running for tasks to execute."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "name" => %{
            "type" => "string",
            "description" => "Human-readable name for the task"
          },
          "prompt" => %{
            "type" => "string",
            "description" => "The prompt to execute"
          },
          "agent" => %{
            "type" => "string",
            "description" => "Agent to use (e.g., code-puppy, code-reviewer, security-auditor)",
            "default" => "code-puppy"
          },
          "model" => %{
            "type" => "string",
            "description" => "Model to use (empty string for default)",
            "default" => ""
          },
          "schedule_type" => %{
            "type" => "string",
            "description" => "Schedule type: 'interval', 'hourly', 'daily', or 'cron'",
            "default" => "interval"
          },
          "schedule_value" => %{
            "type" => "string",
            "description" => "Schedule value (e.g., '30m', '2h', '1d' for intervals)",
            "default" => "1h"
          },
          "working_directory" => %{
            "type" => "string",
            "description" => "Working directory for the task",
            "default" => "."
          }
        },
        "required" => ["name", "prompt"]
      }
    end

    @impl true
    def invoke(args, _context) do
      # Map Python-style "agent" key to Elixir "agent_name"
      # Convert string keys to atoms for Ecto compatibility
      attrs =
        args
        |> Map.put_new("agent_name", Map.get(args, "agent", "code-puppy"))
        |> Map.delete("agent")
        |> atomize_keys()

      {:ok, %{output: SchedulerTools.create_task(attrs)}}
    end

    # Converts string keys to atom keys for Ecto compatibility.
    # Only converts known safe keys — never user-supplied strings to atoms.
    @known_keys ~w(name prompt agent_name agent model schedule_type schedule_value schedule working_directory enabled log_file description config)a

    defp atomize_keys(map) when is_map(map) do
      Map.new(map, fn
        {key, value} when is_binary(key) ->
          atom_key = String.to_atom(key)
          if atom_key in @known_keys, do: {atom_key, value}, else: {key, value}

        {key, value} ->
          {key, value}
      end)
    end
  end

  defmodule CpSchedulerDeleteTask do
    @moduledoc "Delete a scheduled task by its ID."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_delete_task

    @impl true
    def description do
      "Delete a scheduled task by its ID. Permanently removes the " <>
        "task from the schedule."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "task_id" => %{
            "type" => "string",
            "description" => "The ID of the task to delete"
          }
        },
        "required" => ["task_id"]
      }
    end

    @impl true
    def invoke(args, _context) do
      task_id = Map.get(args, "task_id", "")
      {:ok, %{output: SchedulerTools.delete_task(task_id)}}
    end
  end

  defmodule CpSchedulerToggleTask do
    @moduledoc "Toggle a task's enabled/disabled state."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_toggle_task

    @impl true
    def description do
      "Toggle a task's enabled/disabled state. Disabled tasks remain " <>
        "in the schedule but won't run until re-enabled."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "task_id" => %{
            "type" => "string",
            "description" => "The ID of the task to enable/disable"
          }
        },
        "required" => ["task_id"]
      }
    end

    @impl true
    def invoke(args, _context) do
      task_id = Map.get(args, "task_id", "")
      {:ok, %{output: SchedulerTools.toggle_task(task_id)}}
    end
  end

  defmodule CpSchedulerStatus do
    @moduledoc "Check if the scheduler daemon is running."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_status

    @impl true
    def description do
      "Check if the scheduler daemon is running. Returns detailed " <>
        "status including PID and task counts."
    end

    @impl true
    def parameters do
      %{"type" => "object", "properties" => %{}, "required" => []}
    end

    @impl true
    def invoke(_args, _context) do
      {:ok, %{output: SchedulerTools.scheduler_status()}}
    end
  end

  defmodule CpSchedulerRunTask do
    @moduledoc "Run a scheduled task immediately."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_run_task

    @impl true
    def description do
      "Run a scheduled task immediately. Executes the task right now, " <>
        "regardless of its schedule. Useful for testing or one-off runs."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "task_id" => %{
            "type" => "string",
            "description" => "The ID of the task to run immediately"
          }
        },
        "required" => ["task_id"]
      }
    end

    @impl true
    def invoke(args, _context) do
      task_id = Map.get(args, "task_id", "")
      {:ok, %{output: SchedulerTools.run_task(task_id)}}
    end
  end

  defmodule CpSchedulerViewLog do
    @moduledoc "View the log file for a scheduled task."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_view_log

    @impl true
    def description do
      "View the log file for a scheduled task. Shows the most recent " <>
        "output from task executions."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "task_id" => %{
            "type" => "string",
            "description" => "The ID of the task whose log to view"
          },
          "lines" => %{
            "type" => "integer",
            "description" => "Number of lines to show from the end of the log",
            "default" => 50
          }
        },
        "required" => ["task_id"]
      }
    end

    @impl true
    def invoke(args, _context) do
      task_id = Map.get(args, "task_id", "")
      lines = Map.get(args, "lines", 50)
      {:ok, %{output: SchedulerTools.view_log(task_id, lines)}}
    end
  end

  defmodule CpSchedulerForceCheck do
    @moduledoc "Force an immediate check of scheduled tasks."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :cp_scheduler_force_check

    @impl true
    def description do
      "Force an immediate check of scheduled tasks. Causes the " <>
        "CronScheduler to evaluate all enabled tasks and enqueue " <>
        "any that are due."
    end

    @impl true
    def parameters do
      %{"type" => "object", "properties" => %{}, "required" => []}
    end

    @impl true
    def invoke(_args, _context) do
      {:ok, %{output: SchedulerTools.force_check()}}
    end
  end

end
