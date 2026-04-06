defmodule Mana.HealthTest do
  @moduledoc """
  Tests for shared health introspection in `Mana.Health`.
  """

  use ExUnit.Case, async: false

  alias Mana.Health

  describe "check/0" do
    test "returns required fields with expected types" do
      info = Health.check()

      assert is_map(info)
      assert is_binary(info.status)
      assert info.status in ["healthy", "degraded"]
      assert is_integer(info.children)
      assert info.children >= 0
      assert is_binary(info.version)
      assert info.version == Mana.version()
    end

    test "children count matches supervisor active children when supervisor exists" do
      info = Health.check()

      pid = Process.whereis(Mana.Supervisor)

      if pid do
        %{active: expected} = Supervisor.count_children(pid)
        assert info.children == expected
      end
    end
  end

  describe "format_status/0" do
    test "returns terminal-friendly formatted output" do
      output = Health.format_status()

      assert is_binary(output)
      assert output =~ "System Status"
      assert output =~ "Status:"
      assert output =~ "Children:"
      assert output =~ "Version:"
    end
  end

  describe "determine_health_status/1" do
    test "returns degraded for zero children" do
      assert Health.determine_health_status(0) == "degraded"
    end

    test "returns degraded for invalid values" do
      assert Health.determine_health_status(nil) == "degraded"
      assert Health.determine_health_status("bad") == "degraded"
    end

    test "returns healthy for values at/above threshold" do
      assert Health.determine_health_status(3) == "healthy"
      assert Health.determine_health_status(10) == "healthy"
    end

    test "returns degraded for positive values below threshold" do
      assert Health.determine_health_status(1) == "degraded"
      assert Health.determine_health_status(2) == "degraded"
    end
  end
end
