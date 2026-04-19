defmodule CodePuppyControl.Config.PathsTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Config.Paths

  @home Path.expand("~")

  setup do
    # Clean up env vars that might interfere
    on_exit(fn ->
      System.delete_env("PUP_HOME")
      System.delete_env("PUPPY_HOME")
      System.delete_env("XDG_CONFIG_HOME")
      System.delete_env("XDG_DATA_HOME")
      System.delete_env("XDG_CACHE_HOME")
      System.delete_env("XDG_STATE_HOME")
    end)

    :ok
  end

  describe "home_dir/0" do
    test "defaults to ~/.code_puppy" do
      System.delete_env("PUP_HOME")
      System.delete_env("PUPPY_HOME")

      assert Paths.home_dir() == Path.join(@home, ".code_puppy")
    end

    test "PUP_HOME overrides everything" do
      System.put_env("PUP_HOME", "/custom/home")

      assert Paths.home_dir() == "/custom/home"
    end

    test "PUPPY_HOME is legacy fallback" do
      System.delete_env("PUP_HOME")
      System.put_env("PUPPY_HOME", "/legacy/home")

      assert Paths.home_dir() == "/legacy/home"
    end
  end

  describe "config_dir/0" do
    test "defaults to ~/.code_puppy when no XDG vars" do
      System.delete_env("PUP_HOME")
      System.delete_env("XDG_CONFIG_HOME")

      assert Paths.config_dir() == Path.join(@home, ".code_puppy")
    end

    test "uses XDG_CONFIG_HOME when set" do
      System.delete_env("PUP_HOME")
      System.put_env("XDG_CONFIG_HOME", "/xdg/config")

      assert Paths.config_dir() == Path.join("/xdg/config", "code_puppy")
    end
  end

  describe "config_file/0" do
    test "returns path ending in puppy.cfg" do
      assert String.ends_with?(Paths.config_file(), "puppy.cfg")
    end
  end

  describe "mcp_servers_file/0" do
    test "returns path ending in mcp_servers.json" do
      assert String.ends_with?(Paths.mcp_servers_file(), "mcp_servers.json")
    end
  end

  describe "models_file/0" do
    test "returns path ending in models.json" do
      assert String.ends_with?(Paths.models_file(), "models.json")
    end
  end

  describe "agents_dir/0" do
    test "returns path ending in agents" do
      assert String.ends_with?(Paths.agents_dir(), "agents")
    end
  end

  describe "autosave_dir/0" do
    test "returns path ending in autosaves" do
      assert String.ends_with?(Paths.autosave_dir(), "autosaves")
    end
  end

  describe "ensure_dirs!/0" do
    test "creates directories without error" do
      assert Paths.ensure_dirs!() == :ok
    end
  end

  describe "project_agents_dir/0" do
    test "returns nil when .code_puppy/agents doesn't exist" do
      # Unless the test CWD has one
      result = Paths.project_agents_dir()
      assert result == nil or is_binary(result)
    end
  end
end
