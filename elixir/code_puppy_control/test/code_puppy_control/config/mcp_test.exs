defmodule CodePuppyControl.Config.MCPTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.Config.MCP

  setup do
    # Clear cache before each test
    MCP.clear_cache()
    :ok
  end

  describe "load_server_configs/0" do
    test "returns empty map when file doesn't exist" do
      # Use a non-existent path
      temp_file = Path.join(System.tmp_dir!(), "nonexistent_mcp_#{System.unique_integer()}.json")

      # Temporarily override the path
      Application.put_env(:code_puppy_control, :mcp_servers_file_override, temp_file)

      assert MCP.load_server_configs() == %{}

      # Cleanup
      Application.delete_env(:code_puppy_control, :mcp_servers_file_override)
    end

    test "returns empty map when file is empty" do
      temp_file = Path.join(System.tmp_dir!(), "empty_mcp_#{System.unique_integer()}.json")
      File.write!(temp_file, "")

      Application.put_env(:code_puppy_control, :mcp_servers_file_override, temp_file)
      MCP.clear_cache()

      assert MCP.load_server_configs() == %{}

      File.rm!(temp_file)
      Application.delete_env(:code_puppy_control, :mcp_servers_file_override)
    end

    test "parses valid MCP servers config" do
      temp_file = Path.join(System.tmp_dir!(), "valid_mcp_#{System.unique_integer()}.json")

      config_content = """
      {
        "mcp_servers": {
          "test_server": "http://localhost:8080",
          "another_server": {
            "url": "http://localhost:9000",
            "auth": "bearer_token"
          }
        }
      }
      """

      File.write!(temp_file, config_content)

      Application.put_env(:code_puppy_control, :mcp_servers_file_override, temp_file)
      MCP.clear_cache()

      servers = MCP.load_server_configs()
      assert %{"test_server" => "http://localhost:8080"} = servers

      assert %{"another_server" => %{"url" => "http://localhost:9000", "auth" => "bearer_token"}} =
               servers

      File.rm!(temp_file)
      Application.delete_env(:code_puppy_control, :mcp_servers_file_override)
    end

    test "caches results and doesn't re-read unchanged file" do
      temp_file = Path.join(System.tmp_dir!(), "cache_mcp_#{System.unique_integer()}.json")

      config_content = """
      {
        "mcp_servers": {
          "cached_server": "http://localhost:8080"
        }
      }
      """

      File.write!(temp_file, config_content)

      Application.put_env(:code_puppy_control, :mcp_servers_file_override, temp_file)
      MCP.clear_cache()

      # First load
      servers1 = MCP.load_server_configs()
      assert %{"cached_server" => "http://localhost:8080"} = servers1

      # Second load should use cache (mtime unchanged)
      servers2 = MCP.load_server_configs()
      assert servers1 == servers2

      File.rm!(temp_file)
      Application.delete_env(:code_puppy_control, :mcp_servers_file_override)
    end

    test "reload/0 forces re-read from disk" do
      temp_file = Path.join(System.tmp_dir!(), "reload_mcp_#{System.unique_integer()}.json")

      config_content1 = """
      {
        "mcp_servers": {
          "server1": "http://localhost:8080"
        }
      }
      """

      config_content2 = """
      {
        "mcp_servers": {
          "server2": "http://localhost:9000"
        }
      }
      """

      File.write!(temp_file, config_content1)

      Application.put_env(:code_puppy_control, :mcp_servers_file_override, temp_file)
      MCP.clear_cache()

      servers1 = MCP.load_server_configs()
      assert %{"server1" => "http://localhost:8080"} = servers1

      # Update file
      File.write!(temp_file, config_content2)
      # Ensure mtime changes
      :timer.sleep(10)

      servers2 = MCP.reload()
      assert %{"server2" => "http://localhost:9000"} = servers2

      File.rm!(temp_file)
      Application.delete_env(:code_puppy_control, :mcp_servers_file_override)
    end
  end

  describe "get_server/1" do
    test "returns nil for unknown server" do
      assert MCP.get_server("unknown_server") == nil
    end

    test "returns server config for known server" do
      temp_file = Path.join(System.tmp_dir!(), "get_server_mcp_#{System.unique_integer()}.json")

      config_content = """
      {
        "mcp_servers": {
          "my_server": "http://localhost:8080"
        }
      }
      """

      File.write!(temp_file, config_content)

      Application.put_env(:code_puppy_control, :mcp_servers_file_override, temp_file)
      MCP.clear_cache()

      assert MCP.get_server("my_server") == "http://localhost:8080"
      assert MCP.get_server("nonexistent") == nil

      File.rm!(temp_file)
      Application.delete_env(:code_puppy_control, :mcp_servers_file_override)
    end
  end

  describe "disabled?/0" do
    test "returns false by default" do
      assert MCP.disabled?() == false
    end

    test "returns true when disable_mcp is set" do
      # This tests the delegation to Debug.mcp_disabled?()
      # which reads from config
      assert CodePuppyControl.Config.Debug.mcp_disabled?() == false
    end
  end

  describe "clear_cache/0" do
    test "clears cached config" do
      temp_file = Path.join(System.tmp_dir!(), "clear_cache_mcp_#{System.unique_integer()}.json")

      config_content = """
      {
        "mcp_servers": {
          "test": "http://localhost:8080"
        }
      }
      """

      File.write!(temp_file, config_content)

      Application.put_env(:code_puppy_control, :mcp_servers_file_override, temp_file)
      MCP.clear_cache()

      # Load into cache
      MCP.load_server_configs()

      # Clear cache
      assert :ok = MCP.clear_cache()

      # Next load should re-read from disk
      File.rm!(temp_file)
      Application.delete_env(:code_puppy_control, :mcp_servers_file_override)
    end
  end
end
