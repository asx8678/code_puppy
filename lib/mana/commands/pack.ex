defmodule Mana.Commands.Pack do
  @moduledoc """
  Pack workflow commands for parallel multi-agent development.

  Controls the Pack.Leader GenServer to orchestrate workflows that
  fetch issues, plan work, dispatch agents, review, and merge.

  ## Commands

  - `/pack start` - Start a pack workflow (fetches issues, plans, dispatches agents)
  - `/pack status` - Show current workflow state and progress
  - `/pack stop` - Abort the current workflow (resets to idle)

  ## Examples

      /pack start
      # Starts workflow: planning → executing → reviewing → merging → done

      /pack status
      # Shows: State: executing | 2/5 completed | 0 failed | elapsed: 12s

      /pack stop
      # Aborts the workflow and resets to idle
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Pack.Leader

  @leader_name Mana.Pack.Leader

  # ANSI colors
  @cyan "\e[36m"
  @green "\e[32m"
  @red "\e[31m"
  @yellow "\e[33m"
  @magenta "\e[35m"
  @bold "\e[1m"
  @reset "\e[0m"

  @impl true
  def name, do: "/pack"

  @impl true
  def description, do: "Manage pack workflows (start/status/stop)"

  @impl true
  def usage, do: "/pack [start|status|stop]"

  @impl true
  def execute(["start"], _context) do
    with {:alive, true} <- {:alive, leader_alive?()},
         {:state, :idle} <- {:state, get_leader_state()} do
      max_parallel = Mana.Plugins.PackParallelism.get_max_parallel()

      :ok = Leader.run_workflow(@leader_name, max_parallel: max_parallel)

      {:ok,
       "#{@green}#{@bold}Pack workflow started!#{@reset}\n" <>
         "  Max parallel agents: #{max_parallel}\n" <>
         "  Use #{@cyan}/pack status#{@reset} to monitor progress."}
    else
      {:alive, false} ->
        {:error, "Pack Leader is not running. Start the application first."}

      {:state, current} when current != :idle ->
        {:error,
         "Pack Leader is busy (state: #{current}). " <>
           "Use #{@cyan}/pack stop#{@reset} to abort, then try again."}
    end
  end

  def execute(["status"], _context) do
    case leader_alive?() do
      false ->
        {:ok, "#{@red}Pack Leader is not running.#{@reset}"}

      true ->
        case Leader.get_status(@leader_name) do
          {:ok, status} ->
            {:ok, format_status(status)}

          {:error, reason} ->
            {:error, "Failed to get status: #{inspect(reason)}"}
        end
    end
  end

  def execute(["stop"], _context) do
    case leader_alive?() do
      false ->
        {:ok, "#{@yellow}Pack Leader is not running.#{@reset}"}

      true ->
        current_state = get_leader_state()

        # Stop the GenServer — supervisor restarts it fresh in :idle
        case Leader.stop(@leader_name) do
          :ok ->
            {:ok,
             "#{@yellow}#{@bold}Pack workflow aborted.#{@reset}\n" <>
               "  Previous state: #{format_state(current_state)}\n" <>
               "  Leader has been reset to #{@green}:idle#{@reset}."}

          {:error, reason} ->
            {:error, "Failed to stop leader: #{inspect(reason)}"}
        end
    end
  end

  def execute([], _context) do
    {:ok, help_text()}
  end

  def execute(_args, _context) do
    {:error, "Unknown subcommand. #{usage()}"}
  end

  # ── Helpers ──────────────────────────────────────────────

  defp leader_alive? do
    GenServer.whereis(@leader_name) != nil
  end

  defp get_leader_state do
    case Leader.get_status(@leader_name) do
      {:ok, %{state: state}} -> state
      _ -> :unknown
    end
  end

  defp format_status(status) do
    %{
      state: state,
      tasks: tasks,
      progress: {completed, total},
      failed_count: failed,
      started_at: started_at,
      completed_at: completed_at,
      elapsed_ms: elapsed_ms,
      base_branch: base_branch,
      errors: errors
    } = status

    active = Enum.count(tasks, fn {_, t} -> t.status == :pending end)
    approved = Enum.count(tasks, fn {_, t} -> t.status == :approved end)

    lines = [
      format_header(state),
      "  Base branch: #{base_branch}",
      "  #{format_progress_bar(completed, total)}",
      "  Tasks: #{completed}/#{total} completed, #{active} active, #{failed} failed, #{approved} approved",
      format_elapsed(elapsed_ms, started_at, completed_at)
    ]

    lines =
      if errors != [] do
        error_lines = Enum.map(errors, fn e -> "    #{inspect(e)}" end)
        lines ++ ["  #{@red}Errors:#{@reset}"] ++ error_lines
      else
        lines
      end

    lines =
      if map_size(tasks) > 0 do
        lines ++ ["", "  #{format_task_table(tasks)}"]
      else
        lines
      end

    Enum.join(lines, "\n")
  end

  defp format_header(state) do
    state_str = format_state(state)
    "#{@bold}#{@cyan}🐺 Pack Leader#{@reset}  State: #{state_str}"
  end

  defp format_state(:idle), do: "#{@green}:idle#{@reset}"
  defp format_state(:planning), do: "#{@magenta}:planning#{@reset}"
  defp format_state(:executing), do: "#{@yellow}:executing#{@reset}"
  defp format_state(:reviewing), do: "#{@cyan}:reviewing#{@reset}"
  defp format_state(:merging), do: "#{@magenta}:merging#{@reset}"
  defp format_state(:done), do: "#{@green}:done#{@reset}"
  defp format_state(other), do: "#{other}"

  defp format_progress_bar(_completed, 0) do
    "#{@yellow}No tasks#{@reset}"
  end

  defp format_progress_bar(completed, total) do
    pct = div(completed * 100, total)
    filled = div(completed * 20, total)
    empty = 20 - filled

    bar =
      "#{@green}#{String.duplicate("█", filled)}#{@reset}#{String.duplicate("░", empty)}"

    "#{bar} #{pct}% (#{completed}/#{total})"
  end

  defp format_elapsed(nil, nil, _completed_at) do
    "  Not started"
  end

  defp format_elapsed(ms, _started_at, nil) do
    "  Elapsed: #{format_duration(ms)}"
  end

  defp format_elapsed(ms, _started_at, _completed_at) do
    "  Duration: #{format_duration(ms)}"
  end

  defp format_duration(ms) when ms < 1_000, do: "#{ms}ms"
  defp format_duration(ms) when ms < 60_000, do: "#{div(ms, 1_000)}s"
  defp format_duration(ms), do: "#{div(ms, 60_000)}m #{div(rem(ms, 60_000), 1_000)}s"

  defp format_task_table(tasks) do
    tasks
    |> Enum.sort_by(fn {id, _} -> id end)
    |> Enum.map_join("\n", fn {id, task} ->
      status_icon = task_status_icon(task.status)
      verdict_str = format_verdicts(task)

      "  #{status_icon} #{@bold}#{id}#{@reset} #{verdict_str}"
    end)
  end

  defp task_status_icon(:pending), do: "#{@yellow}⧖#{@reset}"
  defp task_status_icon(:completed), do: "#{@green}✓#{@reset}"
  defp task_status_icon(:failed), do: "#{@red}✗#{@reset}"
  defp task_status_icon(:approved), do: "#{@green}★#{@reset}"
  defp task_status_icon(:rejected), do: "#{@red}⊘#{@reset}"
  defp task_status_icon(:merged), do: "#{@green}⊕#{@reset}"
  defp task_status_icon(_), do: "?"

  defp format_verdicts(%{
         shepherd_verdict: sv,
         watchdog_verdict: wv,
         error: err
       }) do
    parts = []

    parts =
      if sv do
        icon = if sv == :approve, do: "#{@green}🐑#{@reset}", else: "#{@red}🐑#{@reset}"
        parts ++ [icon]
      else
        parts
      end

    parts =
      if wv do
        icon = if wv == :approve, do: "#{@green}🐕#{@reset}", else: "#{@red}🐕#{@reset}"
        parts ++ [icon]
      else
        parts
      end

    parts =
      if err do
        parts ++ ["#{@red}err: #{truncate_string(inspect(err), 40)}#{@reset}"]
      else
        parts
      end

    if parts == [], do: "", else: Enum.join(parts, " ")
  end

  defp truncate_string(str, max_len) when byte_size(str) > max_len do
    String.slice(str, 0, max_len) <> "…"
  end

  defp truncate_string(str, _max_len), do: str

  defp help_text do
    """
    #{@bold}#{@cyan}🐺 Pack Leader#{@reset} — Parallel multi-agent workflow orchestration

    #{@bold}Subcommands:#{@reset}

      #{@green}/pack start#{@reset}  Start a pack workflow (fetches issues, plans, dispatches agents)
      #{@cyan}/pack status#{@reset} Show current workflow state and progress
      #{@yellow}/pack stop#{@reset}   Abort the current workflow (resets to idle)

    #{@bold}Workflow states:#{@reset}
      :idle → :planning → :executing → :reviewing → :merging → :done

    #{@bold}Tip:#{@reset} Use #{@cyan}/pack-parallel N#{@reset} to set max concurrent agents.
    """
  end
end
