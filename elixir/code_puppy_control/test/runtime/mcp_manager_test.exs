defmodule CodePuppyControl.Runtime.MCPManagerTest do
  @moduledoc """
  Tests for MCP.Manager — high-level MCP server management API.

  Tests the Manager's API contract (register, unregister, list, stats)
  without requiring actual MCP servers. Server-starting paths are covered
  in integration tests.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.MCP.Manager

  # ---------------------------------------------------------------------------
  # Listing & Stats (no servers required)
  # ---------------------------------------------------------------------------

  describe "list_servers/0" do
    test "returns a list" do
      assert is_list(Manager.list_servers())
    end
  end

  describe "stats/0" do
    test "returns stats map with expected keys" do
      stats = Manager.stats()

      assert Map.has_key?(stats, :total)
      assert Map.has_key?(stats, :healthy)
      assert Map.has_key?(stats, :degraded)
      assert Map.has_key?(stats, :unhealthy)
      assert Map.has_key?(stats, :quarantined)
    end
  end

  describe "get_server_status/1" do
    test "returns error for nonexistent server" do
      result =
        try do
          Manager.get_server_status("nonexistent-xyz-999")
        catch
          :exit, _ -> {:error, :not_found}
        end

      assert match?({:error, _}, result)
    end
  end

  describe "unregister_server/1" do
    test "returns error for nonexistent server" do
      assert {:error, :not_found} = Manager.unregister_server("nonexistent-xyz-999")
    end
  end

  describe "call_tool/4" do
    test "returns error for nonexistent server" do
      result =
        try do
          Manager.call_tool("nonexistent-xyz", "read_file", %{})
        catch
          :exit, _ -> {:error, :not_found}
        end

      assert match?({:error, _}, result)
    end
  end

  describe "health_check_all/0" do
    test "returns a list" do
      assert is_list(Manager.health_check_all())
    end
  end

  describe "stop_all/0" do
    test "returns :ok" do
      assert :ok = Manager.stop_all()
    end
  end
end
