defmodule Mana.Commands.Stats do
  @moduledoc """
  /stats command — display formatted session telemetry metrics.

  Shows aggregated statistics for:
  - Agent runs: count, average duration, success rate
  - Tool calls: count by tool name, average duration
  - Model requests: count by provider, total tokens, average latency
  - Error summary
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.TelemetryHandler

  @impl true
  def name, do: "/stats"

  @impl true
  def description, do: "Show session telemetry statistics"

  @impl true
  def usage, do: "/stats"

  @impl true
  def execute([], _context) do
    stats = TelemetryHandler.get_stats()
    {:ok, format_stats(stats)}
  end

  def execute(_args, _context) do
    {:error, "Usage: #{usage()}"}
  end

  # ── Formatting ────────────────────────────────────────────────

  defp format_stats(stats) do
    sections = [
      format_header(),
      format_agents(stats.agents),
      format_tools(stats.tools),
      format_models(stats.models),
      format_errors(stats)
    ]

    sections
    |> Enum.reject(&is_nil/1)
    |> Enum.join("\n\n")
  end

  defp format_header do
    bold(" Mana Session Statistics ")
    |> then(&"#{border_line()}#{&1}#{border_line()}")
  end

  defp border_line do
    "┌#{String.duplicate("─", 50)}┐\n"
  end

  defp format_agents(%{count: 0}) do
    "  #{dim("Agent Runs:")}  none"
  end

  defp format_agents(%{
         count: count,
         total_duration: total_duration,
         success_count: success_count,
         error_count: error_count
       }) do
    avg_duration = native_to_ms(total_duration, count)
    success_rate = Float.round(success_count / count * 100, 1)

    lines = [
      bold("  Agent Runs"),
      "    Total runs:    #{count}",
      "    Avg duration:  #{avg_duration} ms",
      "    Success rate:  #{colorize_rate(success_rate)}#{success_rate}%",
      "    Successes:     #{success_count}",
      "    Errors:        #{error_count}"
    ]

    Enum.join(lines, "\n")
  end

  defp format_tools(%{count: 0}) do
    "  #{dim("Tool Calls:")}  none"
  end

  defp format_tools(%{count: count, total_duration: total_duration, error_count: error_count, by_tool: by_tool}) do
    avg_duration = native_to_ms(total_duration, count)

    lines = [
      bold("  Tool Calls"),
      "    Total calls:   #{count}",
      "    Avg duration:  #{avg_duration} ms",
      "    Errors:        #{error_count}"
    ]

    lines =
      if map_size(by_tool) > 0 do
        lines ++
          ["", "    #{dim("Per-tool breakdown:")}"] ++
          (by_tool
           |> Enum.sort_by(fn {_name, %{count: c}} -> c end, :desc)
           |> Enum.map(fn {name, %{count: c, total_duration: d, error_count: e}} ->
             avg = native_to_ms(d, c)
             err_str = if e > 0, do: red(" (#{e} errors)"), else: ""
             "      #{pad_name(name, 24)} #{c} calls  avg #{avg} ms#{err_str}"
           end))
      else
        lines
      end

    Enum.join(lines, "\n")
  end

  defp format_models(%{count: 0}) do
    "  #{dim("Model Requests:")}  none"
  end

  defp format_models(%{
         count: count,
         total_duration: total_duration,
         total_tokens_in: tokens_in,
         total_tokens_out: tokens_out,
         error_count: error_count,
         by_provider: by_provider
       }) do
    avg_latency = native_to_ms(total_duration, count)

    lines = [
      bold("  Model Requests"),
      "    Total requests: #{count}",
      "    Avg latency:    #{avg_latency} ms",
      "    Tokens in:      #{format_number(tokens_in)}",
      "    Tokens out:     #{format_number(tokens_out)}",
      "    Errors:         #{error_count}"
    ]

    lines =
      if map_size(by_provider) > 0 do
        lines ++
          ["", "    #{dim("Per-provider breakdown:")}"] ++
          (by_provider
           |> Enum.sort_by(fn {_name, %{count: c}} -> c end, :desc)
           |> Enum.map(fn {name,
                           %{count: c, total_duration: d, total_tokens_in: ti, total_tokens_out: to, error_count: e}} ->
             avg = native_to_ms(d, c)
             total_t = ti + to
             err_str = if e > 0, do: red(" (#{e} errors)"), else: ""
             "      #{pad_name(name, 14)} #{c} reqs  avg #{avg} ms  #{format_number(total_t)} tokens#{err_str}"
           end))
      else
        lines
      end

    Enum.join(lines, "\n")
  end

  defp format_errors(%{agents: %{error_count: 0}, tools: %{error_count: 0}, models: %{error_count: 0}}) do
    nil
  end

  defp format_errors(%{agents: %{error_count: ae}, tools: %{error_count: te}, models: %{error_count: me}}) do
    lines = [
      bold("  Error Summary"),
      "    Agent errors: #{ae}",
      "    Tool errors:  #{te}",
      "    Model errors: #{me}"
    ]

    Enum.join(lines, "\n")
  end

  # ── Helpers ───────────────────────────────────────────────────

  defp native_to_ms(total, count) when count > 0 do
    ms = System.convert_time_unit(total, :native, :millisecond) / count
    Float.round(ms, 1)
  end

  defp native_to_ms(_total, _count), do: 0.0

  defp format_number(n) when n >= 1_000_000 do
    Float.round(n / 1_000_000, 1) |> (fn f -> "#{f}M" end).()
  end

  defp format_number(n) when n >= 1_000 do
    Float.round(n / 1_000, 1) |> (fn f -> "#{f}K" end).()
  end

  defp format_number(n), do: to_string(n)

  defp pad_name(name, width) do
    padding = max(width - String.length(name), 0)
    name <> String.duplicate(" ", padding)
  end

  defp colorize_rate(rate) when rate >= 90, do: green()
  defp colorize_rate(rate) when rate >= 70, do: yellow()
  defp colorize_rate(_rate), do: red()

  # ── ANSI helpers ──────────────────────────────────────────────

  defp bold(text), do: "\e[1m#{text}\e[0m"
  defp dim(text), do: "\e[2m#{text}\e[0m"
  defp red(text), do: "\e[31m#{text}\e[0m"

  defp green, do: "\e[32m"
  defp yellow, do: "\e[33m"
  defp red, do: "\e[31m"
end
