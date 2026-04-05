defmodule Mana.Scheduler.CronTest do
  use ExUnit.Case, async: true

  alias Mana.Scheduler.Cron

  describe "parse_interval/1" do
    test "parses seconds" do
      assert {:ok, 45} == Cron.parse_interval("45s")
    end

    test "parses minutes" do
      assert {:ok, 1800} == Cron.parse_interval("30m")
    end

    test "parses hours" do
      assert {:ok, 3600} == Cron.parse_interval("1h")
      assert {:ok, 21600} == Cron.parse_interval("6h")
    end

    test "parses days" do
      assert {:ok, 172_800} == Cron.parse_interval("2d")
    end

    test "returns error for invalid interval" do
      assert {:error, :invalid_interval} == Cron.parse_interval("abc")
      assert {:error, :invalid_interval} == Cron.parse_interval("")
      assert {:error, :invalid_interval} == Cron.parse_interval("5x")
    end
  end

  describe "matches?/2 — cron expressions" do
    test "matches every minute wildcard" do
      assert Cron.matches?("* * * * *", ~U[2024-01-01 10:30:00Z])
    end

    test "matches specific minute" do
      assert Cron.matches?("30 * * * *", ~U[2024-01-01 10:30:00Z])
      refute Cron.matches?("30 * * * *", ~U[2024-01-01 10:15:00Z])
    end

    test "matches specific hour and minute" do
      assert Cron.matches?("0 9 * * *", ~U[2024-01-01 09:00:00Z])
      refute Cron.matches?("0 9 * * *", ~U[2024-01-01 10:00:00Z])
    end

    test "matches step expressions (*/N)" do
      assert Cron.matches?("*/15 * * * *", ~U[2024-01-01 10:00:00Z])
      assert Cron.matches?("*/15 * * * *", ~U[2024-01-01 10:15:00Z])
      assert Cron.matches?("*/15 * * * *", ~U[2024-01-01 10:30:00Z])
      assert Cron.matches?("*/15 * * * *", ~U[2024-01-01 10:45:00Z])
      refute Cron.matches?("*/15 * * * *", ~U[2024-01-01 10:10:00Z])
    end

    test "matches range expressions (N-M)" do
      # Monday=1 through Friday=5
      # 2024-01-01 is Monday
      assert Cron.matches?("0 9 * * 1-5", ~U[2024-01-01 09:00:00Z])
      # 2024-01-06 is Saturday
      refute Cron.matches?("0 9 * * 1-5", ~U[2024-01-06 09:00:00Z])
    end

    test "matches list expressions (N,M,O)" do
      assert Cron.matches?("0,30 * * * *", ~U[2024-01-01 10:00:00Z])
      assert Cron.matches?("0,30 * * * *", ~U[2024-01-01 10:30:00Z])
      refute Cron.matches?("0,30 * * * *", ~U[2024-01-01 10:15:00Z])
    end

    test "matches specific month" do
      assert Cron.matches?("0 0 1 6 *", ~U[2024-06-01 00:00:00Z])
      refute Cron.matches?("0 0 1 6 *", ~U[2024-07-01 00:00:00Z])
    end

    test "returns false for interval notation (requires should_run?)" do
      # Intervals need last_run context
      refute Cron.matches?("30m", ~U[2024-01-01 10:00:00Z])
    end
  end

  describe "should_run?/3 — interval schedules" do
    test "runs immediately if never run before" do
      assert Cron.should_run?("30m", nil, ~U[2024-01-01 10:00:00Z])
    end

    test "runs when interval has elapsed" do
      last_run = ~U[2024-01-01 09:00:00Z]
      now = ~U[2024-01-01 09:35:00Z]
      assert Cron.should_run?("30m", last_run, now)
    end

    test "does not run before interval elapses" do
      last_run = ~U[2024-01-01 09:00:00Z]
      now = ~U[2024-01-01 09:20:00Z]
      refute Cron.should_run?("30m", last_run, now)
    end

    test "hourly interval" do
      last_run = ~U[2024-01-01 09:00:00Z]
      now = ~U[2024-01-01 10:01:00Z]
      assert Cron.should_run?("1h", last_run, now)

      now2 = ~U[2024-01-01 09:30:00Z]
      refute Cron.should_run?("1h", last_run, now2)
    end
  end

  describe "should_run?/3 — cron schedules" do
    test "runs when cron matches and not same minute as last_run" do
      last_run = ~U[2024-01-01 09:00:00Z]
      now = ~U[2024-01-01 10:00:00Z]
      assert Cron.should_run?("0 * * * *", last_run, now)
    end

    test "does not run in same minute as last_run" do
      last_run = ~U[2024-01-01 10:00:00Z]
      now = ~U[2024-01-01 10:00:30Z]
      refute Cron.should_run?("0 * * * *", last_run, now)
    end

    test "runs when never run before and cron matches" do
      now = ~U[2024-01-01 10:00:00Z]
      assert Cron.should_run?("0 * * * *", nil, now)
    end

    test "does not run when cron does not match" do
      now = ~U[2024-01-01 10:15:00Z]
      refute Cron.should_run?("0 * * * *", nil, now)
    end
  end

  describe "next_run/2" do
    test "returns next interval time from now" do
      now = ~U[2024-01-01 10:00:00Z]
      assert {:ok, next} = Cron.next_run("30m", now)
      assert next == ~U[2024-01-01 10:30:00Z]
    end

    test "finds next cron match" do
      # 0 9 * * * = 9:00 AM daily
      now = ~U[2024-01-01 08:30:00Z]
      assert {:ok, next} = Cron.next_run("0 9 * * *", now)
      assert next == ~U[2024-01-01 09:00:00Z]
    end

    test "finds next cron match later today" do
      # */30 * * * * = every 30 minutes
      now = ~U[2024-01-01 10:10:00Z]
      assert {:ok, next} = Cron.next_run("*/30 * * * *", now)
      assert next == ~U[2024-01-01 10:30:00Z]
    end
  end

  describe "next_run/3" do
    test "returns next interval from last_run" do
      last_run = ~U[2024-01-01 09:00:00Z]
      now = ~U[2024-01-01 09:20:00Z]

      assert {:ok, next} = Cron.next_run("1h", last_run, now)
      assert next == ~U[2024-01-01 10:00:00Z]
    end

    test "returns next from now when no last_run" do
      now = ~U[2024-01-01 09:20:00Z]
      assert {:ok, next} = Cron.next_run("30m", nil, now)
      assert next == ~U[2024-01-01 09:50:00Z]
    end
  end

  describe "job_due?/2" do
    alias Mana.Scheduler.Job

    test "disabled jobs are never due" do
      job = Job.new(name: "test", schedule: "1h", agent: "bot", prompt: "hi")
      job = %{job | enabled: false}

      refute Cron.job_due?(job, DateTime.utc_now())
    end

    test "enabled job with no last_run is due" do
      job = Job.new(name: "test", schedule: "1h", agent: "bot", prompt: "hi")
      assert Cron.job_due?(job, DateTime.utc_now())
    end
  end
end
