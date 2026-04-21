defmodule CodePuppyControl.Runtime.MCPManagerTest do
  @moduledoc """
  Tests for MCP.Manager — high-level MCP server management API.

  Tests the Manager's API contract (register, unregister, list, stats)
  without requiring actual MCP servers. Server-starting paths are covered
  in integration tests.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.MCP.Manager

  @tmp_dir System.tmp_dir!()
  @test_home Path.join(@tmp_dir, "mcp_manager_test_#{:erlang.unique_integer([:positive])}")

  setup do
    File.mkdir_p!(@test_home)

    orig_pup_ex = System.get_env("PUP_EX_HOME")
    orig_pup_home = System.get_env("PUP_HOME")
    orig_puppy_home = System.get_env("PUPPY_HOME")

    System.put_env("PUP_EX_HOME", @test_home)
    System.delete_env("PUP_HOME")
    System.delete_env("PUPPY_HOME")

    on_exit(fn ->
      if orig_pup_ex,
        do: System.put_env("PUP_EX_HOME", orig_pup_ex),
        else: System.delete_env("PUP_EX_HOME")

      if orig_pup_home,
        do: System.put_env("PUP_HOME", orig_pup_home),
        else: System.delete_env("PUP_HOME")

      if orig_puppy_home,
        do: System.put_env("PUPPY_HOME", orig_puppy_home),
        else: System.delete_env("PUPPY_HOME")

      File.rm_rf!(@test_home)
    end)

    :ok
  end

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

  # ---------------------------------------------------------------------------
  # Config-driven lifecycle helpers
  # ---------------------------------------------------------------------------

  describe "read_configured_servers/0" do
    test "returns empty list when no config file exists" do
      File.rm(Path.join(@test_home, "mcp_servers.json"))
      assert [] = Manager.read_configured_servers()
    end

    test "reads flat server config from disk" do
      File.mkdir_p!(@test_home)

      File.write!(
        Path.join(@test_home, "mcp_servers.json"),
        Jason.encode!(%{
          "filesystem" => %{"command" => "npx", "args" => ["-y", "mcp-fs"], "env" => %{}},
          "github" => %{"command" => "docker", "args" => [], "env" => %{}}
        })
      )

      servers = Manager.read_configured_servers()
      names = Enum.map(servers, & &1["name"])
      assert "filesystem" in names
      assert "github" in names
    end

    test "reads nested mcp_servers shape" do
      File.mkdir_p!(@test_home)

      File.write!(
        Path.join(@test_home, "mcp_servers.json"),
        Jason.encode!(%{
          "mcp_servers" => %{"deep" => %{"command" => "npx", "args" => [], "env" => %{}}}
        })
      )

      servers = Manager.read_configured_servers()
      names = Enum.map(servers, & &1["name"])
      assert "deep" in names
    end

    test "skips non-map server values" do
      File.mkdir_p!(@test_home)

      File.write!(
        Path.join(@test_home, "mcp_servers.json"),
        Jason.encode!(%{
          "broken" => true,
          "valid" => %{"command" => "echo"}
        })
      )

      servers = Manager.read_configured_servers()
      names = Enum.map(servers, & &1["name"])
      refute "broken" in names
      assert "valid" in names
    end
  end

  describe "find_server_config_by_name/1" do
    test "returns nil for nonexistent server" do
      File.rm(Path.join(@test_home, "mcp_servers.json"))
      assert nil == Manager.find_server_config_by_name("nope")
    end

    test "finds server config case-insensitively" do
      File.mkdir_p!(@test_home)

      File.write!(
        Path.join(@test_home, "mcp_servers.json"),
        Jason.encode!(%{"FileSystem" => %{"command" => "npx"}})
      )

      cfg = Manager.find_server_config_by_name("filesystem")
      assert cfg != nil
      assert cfg["name"] == "FileSystem"
    end
  end

  describe "find_server_id_by_name/1" do
    test "returns not_found when no server running by that name" do
      assert {:error, :not_found} = Manager.find_server_id_by_name("nope")
    end
  end

  describe "start_server_by_name/1" do
    test "returns not_configured when server not in config" do
      File.rm(Path.join(@test_home, "mcp_servers.json"))
      assert {:error, :not_configured} = Manager.start_server_by_name("nope")
    end
  end

  describe "stop_server_by_name/1" do
    test "returns not_running when no server running by that name" do
      assert {:error, :not_running} = Manager.stop_server_by_name("nope")
    end
  end

  describe "restart_server_by_name/1" do
    test "returns not_configured when server not in config" do
      File.rm(Path.join(@test_home, "mcp_servers.json"))
      assert {:error, :not_configured} = Manager.restart_server_by_name("nope")
    end
  end

  describe "start_all_configured/0" do
    test "returns empty list when no servers configured" do
      File.rm(Path.join(@test_home, "mcp_servers.json"))
      assert [] = Manager.start_all_configured()
    end
  end

  describe "stop_all_running/0" do
    test "returns empty list when no servers running" do
      assert [] = Manager.stop_all_running()
    end
  end
end
