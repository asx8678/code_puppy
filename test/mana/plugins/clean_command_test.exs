defmodule Mana.Plugins.CleanCommandTest do
  use ExUnit.Case, async: false

  alias Mana.Plugins.CleanCommand
  alias Mana.Session.Store

  setup do
    temp_dir = System.tmp_dir!()
    test_config = Path.join(temp_dir, "mana_test_config_#{:erlang.unique_integer([:positive])}")
    test_data = Path.join(temp_dir, "mana_test_data_#{:erlang.unique_integer([:positive])}")

    original_config = System.get_env("XDG_CONFIG_HOME")
    original_data = System.get_env("XDG_DATA_HOME")

    System.put_env("XDG_CONFIG_HOME", test_config)
    System.put_env("XDG_DATA_HOME", test_data)

    # Ensure directories exist
    File.mkdir_p!(test_config)
    File.mkdir_p!(test_data)

    # Start the store
    start_supervised!(Store)

    on_exit(fn ->
      if original_config,
        do: System.put_env("XDG_CONFIG_HOME", original_config),
        else: System.delete_env("XDG_CONFIG_HOME")

      if original_data,
        do: System.put_env("XDG_DATA_HOME", original_data),
        else: System.delete_env("XDG_DATA_HOME")

      File.rm_rf!(test_config)
      File.rm_rf!(test_data)
    end)

    :ok
  end

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = CleanCommand.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(CleanCommand, :name, 0)
      assert function_exported?(CleanCommand, :init, 1)
      assert function_exported?(CleanCommand, :hooks, 0)
      assert function_exported?(CleanCommand, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert CleanCommand.name() == "clean_command"
    end
  end

  describe "init/1" do
    test "initializes with config" do
      assert {:ok, state} = CleanCommand.init(%{})
      assert is_map(state.config)
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = CleanCommand.hooks()
      assert is_list(hooks)
      assert length(hooks) == 1

      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :custom_command in hook_names
    end
  end

  describe "handle_clean/2" do
    test "cleans all targets by default" do
      result = CleanCommand.handle_clean("clean", [])
      assert is_binary(result)
      assert result =~ "✓ Sessions cleaned"
      assert result =~ "✓ Logs cleaned"
      assert result =~ "✓ Cache cleaned"
    end

    test "cleans specific target: sessions" do
      result = CleanCommand.handle_clean("clean", ["sessions"])
      assert result =~ "✓ Sessions cleaned"
    end

    test "cleans specific target: logs" do
      result = CleanCommand.handle_clean("clean", ["logs"])
      assert result =~ "✓ Logs cleaned"
    end

    test "cleans specific target: cache" do
      result = CleanCommand.handle_clean("clean", ["cache"])
      assert result =~ "✓ Cache cleaned"
    end

    test "cleans specific target: history" do
      result = CleanCommand.handle_clean("clean", ["history"])
      assert result =~ "✓ History cleaned"
    end

    test "dry-run flag shows what would be cleaned" do
      result = CleanCommand.handle_clean("clean", ["--dry-run"])
      assert result =~ "Would clean"
      refute result =~ "✓"
    end

    test "dry-run with specific target" do
      result = CleanCommand.handle_clean("clean", ["--dry-run", "sessions"])
      assert result == "Would clean sessions"
    end

    test "returns error for unknown target" do
      result = CleanCommand.handle_clean("clean", ["unknown"])
      assert result =~ "Unknown target: unknown"
      assert result =~ "Options: all, sessions, history, logs, cache"
    end

    test "returns nil for unknown command" do
      result = CleanCommand.handle_clean("other-command", [])
      assert result == nil
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert CleanCommand.terminate() == :ok
    end
  end
end
