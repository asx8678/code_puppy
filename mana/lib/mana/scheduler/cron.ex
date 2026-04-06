defmodule Mana.Scheduler.Cron do
  @moduledoc """
  Cron expression evaluator and interval parser.

  Supports two schedule formats:

    * **5-field cron**: `minute hour day_of_month month day_of_week`
    * **Interval shorthand**: `"30s"`, `"15m"`, `"1h"`, `"6h"`, `"2d"`

  ## Cron field syntax

  Each field supports:

    * `*` — any value
    * `*/N` — every N units (e.g., `*/15` in minute field = every 15 min)
    * `N` — exact value
    * `N-M` — range (e.g., `1-5` in weekday = Mon through Fri)
    * `N,M,O` — list of values

  ## Examples

      iex> Mana.Scheduler.Cron.matches?("*/5 * * * *", ~U[2024-01-01 10:05:00Z])
      true

      iex> Mana.Scheduler.Cron.matches?("0 9 * * 1-5", ~U[2024-01-01 09:00:00Z])
      true

      iex> Mana.Scheduler.Cron.should_run?("30m", nil, ~U[2024-01-01 10:00:00Z])
      true
  """

  alias Mana.Scheduler.Job

  @type cron_field :: String.t()

  # ---------------------------------------------------------------------------
  # Public API
  # ---------------------------------------------------------------------------

  @doc """
  Determines if a schedule expression matches the given DateTime.

  Handles both cron expressions and interval notation transparently.

  For interval notation, use `should_run?/3` instead, which takes the
  last_run timestamp into account.
  """
  @spec matches?(String.t(), DateTime.t()) :: boolean()
  def matches?(cron_expr, %DateTime{} = dt) when is_binary(cron_expr) do
    case parse_fields(cron_expr) do
      {:cron, [minute, hour, dom, month, dow]} ->
        field_matches?(minute, dt.minute, 0..59) and
          field_matches?(hour, dt.hour, 0..23) and
          field_matches?(dom, dt.day, 1..31) and
          field_matches?(month, dt.month, 1..12) and
          field_matches?(dow, Date.day_of_week(dt), 1..7)

      {:interval, _} ->
        # Intervals require last_run context — always return false here
        # Use should_run?/3 for interval-based schedules
        false
    end
  end

  @doc """
  Given a cron expression and current time, computes the next DateTime
  that will match the expression.

  For interval notation, computes the next run time based on the last run.

  Returns `{:ok, DateTime.t()}` or `{:error, reason}`.
  """
  @spec next_run(String.t(), DateTime.t()) :: {:ok, DateTime.t()} | {:error, term()}
  def next_run(schedule, %DateTime{} = now) when is_binary(schedule) do
    case parse_fields(schedule) do
      {:cron, _fields} ->
        find_next_cron_match(schedule, now)

      {:interval, seconds} ->
        {:ok, DateTime.add(now, seconds, :second)}
    end
  end

  @doc """
  Given a schedule and last_run time, computes when the next run should occur.
  """
  @spec next_run(String.t(), DateTime.t() | nil, DateTime.t()) ::
          {:ok, DateTime.t()} | {:error, term()}
  def next_run(schedule, last_run, %DateTime{} = now) when is_binary(schedule) do
    case parse_fields(schedule) do
      {:cron, _fields} ->
        # For cron, next run is always the next matching time from now
        find_next_cron_match(schedule, now)

      {:interval, seconds} ->
        base = last_run || now
        {:ok, DateTime.add(base, seconds, :second)}
    end
  end

  @doc """
  Determines whether a job should run now based on its schedule,
  last run time, and the current time.

  For interval schedules: checks if enough time has elapsed since last_run.
  For cron schedules: checks if the current minute matches the cron expression
  and the job hasn't already run this minute.
  """
  @spec should_run?(String.t(), DateTime.t() | nil, DateTime.t()) :: boolean()
  def should_run?(schedule, last_run, %DateTime{} = now) when is_binary(schedule) do
    case parse_fields(schedule) do
      {:interval, seconds} ->
        case last_run do
          nil -> true
          lr -> DateTime.diff(now, lr, :second) >= seconds
        end

      {:cron, _fields} ->
        if matches?(schedule, now) do
          # Ensure we haven't already fired for this exact minute
          case last_run do
            nil ->
              true

            lr ->
              # Check if last_run is in a different minute than now
              not same_minute?(lr, now)
          end
        else
          false
        end
    end
  end

  @doc """
  Convenience: checks if a Job is due to run.
  """
  @spec job_due?(Job.t(), DateTime.t()) :: boolean()
  def job_due?(%Job{enabled: false}, _now), do: false
  def job_due?(%Job{enabled: true} = job, %DateTime{} = now), do: should_run?(job.schedule, job.last_run, now)

  @doc """
  Parses an interval string like "30m", "1h", "6h" into seconds.

  Returns `{:ok, seconds}` or `{:error, :invalid_interval}`.
  """
  @spec parse_interval(String.t()) :: {:ok, non_neg_integer()} | {:error, :invalid_interval}
  def parse_interval(str) when is_binary(str) do
    case Regex.run(~r/^(\d+)([smhd])$/i, str) do
      [_, value_str, unit] ->
        value = String.to_integer(value_str)

        seconds =
          case String.downcase(unit) do
            "s" -> value
            "m" -> value * 60
            "h" -> value * 3600
            "d" -> value * 86_400
          end

        {:ok, seconds}

      nil ->
        {:error, :invalid_interval}
    end
  end

  # ---------------------------------------------------------------------------
  # Parsing
  # ---------------------------------------------------------------------------

  @doc false
  @spec parse_fields(String.t()) :: {:cron, [cron_field()]} | {:interval, non_neg_integer()}
  def parse_fields(expr) when is_binary(expr) do
    case parse_interval(expr) do
      {:ok, seconds} ->
        {:interval, seconds}

      {:error, :invalid_interval} ->
        # Try as cron expression (5 fields separated by spaces)
        case String.split(expr, ~r/\s+/, trim: true) do
          [minute, hour, dom, month, dow] ->
            {:cron, [minute, hour, dom, month, dow]}

          _ ->
            {:interval, 3600}
        end
    end
  end

  # ---------------------------------------------------------------------------
  # Cron field matching
  # ---------------------------------------------------------------------------

  @spec field_matches?(cron_field(), integer(), Range.t()) :: boolean()
  defp field_matches?("*", _value, _range), do: true

  defp field_matches?(field, value, range) do
    cond do
      # Step: */N or M-N/S
      String.contains?(field, "/") ->
        step_matches?(field, value, range)

      # List: 1,3,5
      String.contains?(field, ",") ->
        list_matches?(field, value)

      # Range: 1-5
      String.contains?(field, "-") ->
        range_matches?(field, value)

      # Exact value
      true ->
        case Integer.parse(field) do
          {n, ""} -> n == value
          _ -> false
        end
    end
  end

  defp step_matches?(field, value, range) do
    case String.split(field, "/", parts: 2) do
      [base, step_str] ->
        step = String.to_integer(step_str)

        case base do
          "*" ->
            range_first = range.first
            rem(value - range_first, step) == 0

          range_base ->
            case String.split(range_base, "-", parts: 2) do
              [start_str, end_str] ->
                start_val = String.to_integer(start_str)
                end_val = String.to_integer(end_str)
                value >= start_val and value <= end_val and rem(value - start_val, step) == 0

              [single] ->
                single_val = String.to_integer(single)
                value >= single_val and rem(value - single_val, step) == 0
            end
        end

      _ ->
        false
    end
  end

  defp list_matches?(field, value) do
    field
    |> String.split(",")
    |> Enum.any?(fn part ->
      case Integer.parse(String.trim(part)) do
        {n, ""} -> n == value
        _ -> false
      end
    end)
  end

  defp range_matches?(field, value) do
    case String.split(field, "-", parts: 2) do
      [start_str, end_str] ->
        start_val = String.to_integer(start_str)
        end_val = String.to_integer(end_str)
        value >= start_val and value <= end_val

      _ ->
        false
    end
  end

  # ---------------------------------------------------------------------------
  # Next cron match finder
  # ---------------------------------------------------------------------------

  defp find_next_cron_match(cron_expr, %DateTime{} = from) do
    # Start from the next minute (round up to next minute boundary)
    start = from |> DateTime.truncate(:second) |> DateTime.add(60, :second)
    # Round down to minute boundary
    start = %{start | second: 0}

    find_next(cron_expr, start, 0)
  end

  # Search forward minute-by-minute (max 525,600 iterations = 1 year)
  defp find_next(_cron_expr, _dt, iterations) when iterations > 525_600 do
    {:error, :no_match_found}
  end

  defp find_next(cron_expr, %DateTime{} = dt, iterations) do
    if matches?(cron_expr, dt) do
      {:ok, dt}
    else
      next = DateTime.add(dt, 60, :second)
      find_next(cron_expr, next, iterations + 1)
    end
  end

  # ---------------------------------------------------------------------------
  # Time helpers
  # ---------------------------------------------------------------------------

  defp same_minute?(%DateTime{} = a, %DateTime{} = b) do
    a.year == b.year and a.month == b.month and a.day == b.day and
      a.hour == b.hour and a.minute == b.minute
  end
end
