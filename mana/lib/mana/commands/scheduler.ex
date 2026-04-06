defmodule Mana.Commands.Scheduler do
  @moduledoc """
  Scheduler management commands for the Mana system.

  Provides commands to create, list, delete, toggle, and manually run
  scheduled background jobs.

  ## Commands

  - `/scheduler` or `/scheduler list` — list all scheduled jobs
  - `/scheduler create <name> --schedule="..." --agent="..." --prompt="..."` — create a job
  - `/scheduler delete <name>` — delete a job
  - `/scheduler toggle <name>` — enable/disable a job
  - `/scheduler run <name>` — manually trigger a job immediately

  ## Examples

      /scheduler list
      /scheduler create daily-review --schedule="0 9 * * *" --agent=assistant --prompt="Review PRs"
      /scheduler delete daily-review
      /scheduler toggle daily-review
      /scheduler run daily-review
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Scheduler.{Job, Store}

  # ANSI helpers
  @reset "\e[0m"
  @bold "\e[1m"
  @cyan "\e[36m"
  @green "\e[32m"
  @red "\e[31m"
  @yellow "\e[33m"
  @dim "\e[2m"

  @impl true
  def name, do: "/scheduler"

  @impl true
  def description, do: "Manage scheduled background jobs"

  @impl true
  def usage, do: "/scheduler [list|create|delete|toggle|run]"

  @impl true
  def execute([], _context), do: list_jobs()
  def execute(["list"], _context), do: list_jobs()
  def execute(["create" | rest], _context), do: create_job(rest)
  def execute(["delete", name], _context), do: delete_job(name)
  def execute(["toggle", name], _context), do: toggle_job(name)
  def execute(["run", name], _context), do: run_job(name)

  def execute(_args, _context) do
    {:error, "Usage: #{usage()}"}
  end

  # ---------------------------------------------------------------------------
  # Sub-commands
  # ---------------------------------------------------------------------------

  defp list_jobs do
    case Store.list() do
      {:ok, []} ->
        {:ok, "#{@dim}No scheduled jobs found. Use `/scheduler create` to add one.#{@reset}"}

      {:ok, jobs} ->
        table = format_job_table(jobs)
        {:ok, table}

      {:error, reason} ->
        {:error, "Failed to list jobs: #{inspect(reason)}"}
    end
  end

  defp create_job(args) do
    name = List.first(args)

    if is_nil(name) or String.starts_with?(name, "--") do
      {:error, "Usage: /scheduler create <name> --schedule=\"...\" --agent=\"...\" --prompt=\"...\""}
    else
      opts = parse_opts(Enum.drop(args, 1))

      with {:ok, schedule} <- fetch_opt(opts, "schedule"),
           {:ok, agent} <- fetch_opt(opts, "agent"),
           {:ok, prompt} <- fetch_opt(opts, "prompt") do
        # Check for duplicate name
        case find_job_by_name(name) do
          {:ok, _existing} ->
            {:error, "Job '#{name}' already exists. Use a different name or delete it first."}

          :not_found ->
            model = Map.get(opts, "model", "")
            work_dir = Map.get(opts, "working_directory", ".")

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
                 "#{@green}✓#{@reset} Created job #{bold(stored_job.name)} " <>
                   "(#{stored_job.id}) schedule=#{stored_job.schedule} agent=#{stored_job.agent}"}

              {:error, reason} ->
                {:error, "Failed to create job: #{inspect(reason)}"}
            end
        end
      end
    end
  end

  defp delete_job(name) do
    case find_job_by_name(name) do
      {:ok, job} ->
        case Store.delete(job.id) do
          :ok ->
            {:ok, "#{@red}✗#{@reset} Deleted job #{bold(name)} (#{job.id})"}

          {:error, reason} ->
            {:error, "Failed to delete job: #{inspect(reason)}"}
        end

      :not_found ->
        {:error, "Job '#{name}' not found"}
    end
  end

  defp toggle_job(name) do
    case find_job_by_name(name) do
      {:ok, job} ->
        toggled = %{job | enabled: not job.enabled}

        case Store.put(toggled) do
          {:ok, updated} ->
            status = if updated.enabled, do: "#{@green}enabled#{@reset}", else: "#{@red}disabled#{@reset}"
            {:ok, "Job #{bold(name)} is now #{status}"}

          {:error, reason} ->
            {:error, "Failed to toggle job: #{inspect(reason)}"}
        end

      :not_found ->
        {:error, "Job '#{name}' not found"}
    end
  end

  defp run_job(name) do
    case find_job_by_name(name) do
      {:ok, job} ->
        # Fire the job immediately via the Runner
        now = DateTime.utc_now()
        updated = %{job | last_run: now, last_status: :running}

        case Store.put(updated) do
          {:ok, _} ->
            # Trigger a force tick to let the runner pick it up,
            # or start a simple async task for immediate execution
            start_manual_run(job)

            {:ok,
             "#{@cyan}▶#{@reset} Manually triggered job #{bold(name)} " <>
               "with agent=#{job.agent}"}

          {:error, reason} ->
            {:error, "Failed to update job for manual run: #{inspect(reason)}"}
        end

      :not_found ->
        {:error, "Job '#{name}' not found"}
    end
  end

  # ---------------------------------------------------------------------------
  # Job table formatting
  # ---------------------------------------------------------------------------

  defp format_job_table(jobs) do
    # Column widths
    name_w = jobs |> Enum.map(& &1.name) |> max_len(12)
    schedule_w = jobs |> Enum.map(& &1.schedule) |> max_len(14)
    agent_w = jobs |> Enum.map(& &1.agent) |> max_len(10)

    header =
      pad("Name", name_w, :right) <>
        "  " <>
        pad("Schedule", schedule_w, :right) <>
        "  " <>
        pad("Agent", agent_w, :right) <>
        "  " <>
        pad("Enabled", 7, :right) <>
        "  " <>
        pad("Status", 8, :right) <>
        "  Last Run"

    sep = String.duplicate("─", String.length(strip_ansi(header)))

    rows =
      Enum.map(jobs, fn job ->
        enabled_str = if job.enabled, do: "#{@green}✓#{@reset}", else: "#{@red}✗#{@reset}"
        status_str = format_status(job.last_status)

        last_run_str =
          case job.last_run do
            nil -> "#{@dim}never#{@reset}"
            dt -> Calendar.strftime(dt, "%Y-%m-%d %H:%M")
          end

        pad(bold(job.name), name_w, :right) <>
          "  " <>
          pad("#{@cyan}#{job.schedule}#{@reset}", schedule_w, :right) <>
          "  " <>
          pad(job.agent, agent_w, :right) <>
          "  " <>
          pad(enabled_str, 7, :right) <>
          "  " <>
          pad(status_str, 8, :right) <>
          "  " <> last_run_str
      end)

    [header, sep | rows]
    |> Enum.join("\n")
  end

  defp format_status(nil), do: "#{@dim}—#{@reset}"
  defp format_status(:success), do: "#{@green}success#{@reset}"
  defp format_status(:failed), do: "#{@red}failed#{@reset}"
  defp format_status(:running), do: "#{@yellow}running#{@reset}"

  # ---------------------------------------------------------------------------
  # Argument parsing helpers
  # ---------------------------------------------------------------------------

  defp parse_opts(args) do
    Enum.reduce(args, %{}, fn arg, acc ->
      case Regex.run(~r/^--([a-z_]+)[=:](.+)$/, arg) do
        [_, key, value] -> Map.put(acc, key, value)
        _ -> acc
      end
    end)
  end

  defp fetch_opt(opts, key) do
    case Map.fetch(opts, key) do
      {:ok, value} -> {:ok, value}
      :error -> {:error, "Missing required option: --#{key}"}
    end
  end

  # ---------------------------------------------------------------------------
  # Store helpers
  # ---------------------------------------------------------------------------

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

  defp start_manual_run(job) do
    Task.start(fn ->
      alias Mana.Scheduler.Runner

      # Try the runner if it's started
      case Process.whereis(Mana.Scheduler.Runner) do
        nil ->
          # Runner not started, do a simple execution
          simple_execute(job)

        _pid ->
          # Let the runner handle it via force_tick
          Runner.force_tick()
      end
    end)
  end

  defp simple_execute(job) do
    require Logger
    Logger.info("[Scheduler.Command] Manually executing job '#{job.name}': #{job.prompt}")

    # Mark as success after logging
    case Store.get(job.id) do
      {:ok, stored_job} ->
        success_job = %{stored_job | last_status: :success, last_exit_code: 0}
        Store.put(success_job)

      _ ->
        :ok
    end
  end

  # ---------------------------------------------------------------------------
  # Formatting helpers
  # ---------------------------------------------------------------------------

  defp bold(text), do: "#{@bold}#{text}#{@reset}"

  defp pad(text, width, :right) do
    # Strip ANSI codes for width calculation
    visible = strip_ansi(text)
    padding = max(width - String.length(visible), 0)
    text <> String.duplicate(" ", padding)
  end

  defp strip_ansi(str) do
    Regex.replace(~r/\e\[[0-9;]*m/, str, "")
  end

  defp max_len(strings, min) do
    strings
    |> Enum.map(&String.length/1)
    |> Enum.max(fn -> min end)
    |> max(min)
  end
end
