defmodule CodePuppyControl.PluginsTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.{Callbacks, Plugins}

  setup do
    Callbacks.clear()
    :ok
  end

  describe "load_plugin/1 with module" do
    test "loads a module that implements PluginBehaviour" do
      assert {:ok, :test_plugin} = Plugins.load_plugin(CodePuppyControl.Test.TestPlugin)
    end

    test "returns error for non-plugin module" do
      assert {:error, {:not_a_plugin, _}} = Plugins.load_plugin(String)
    end
  end

  describe "load_plugin/1 with file path" do
    test "returns error for non-existent file" do
      # Code.compile_file raises RuntimeError for missing files
      assert {:error, {:file_not_found, _}} = Plugins.load_plugin("/nonexistent/plugin.ex")
    end
  end

  describe "list_loaded/0" do
    test "returns empty list when no plugins loaded" do
      assert [] = Plugins.list_loaded()
    end

    test "returns loaded plugin info" do
      Plugins.load_plugin(CodePuppyControl.Test.TestPlugin)

      loaded = Plugins.list_loaded()
      assert length(loaded) >= 1

      test_plugin = Enum.find(loaded, fn p -> p.name == :test_plugin end)
      assert test_plugin != nil
      assert test_plugin.module == CodePuppyControl.Test.TestPlugin
      assert test_plugin.type == :builtin
    end
  end

  describe "user_plugins_dir/0" do
    test "returns a string path" do
      dir = Plugins.user_plugins_dir()
      assert is_binary(dir)
      assert String.contains?(dir, ".code_puppy")
    end
  end

  describe "ensure_user_plugins_dir/0" do
    test "creates the directory if it doesn't exist" do
      dir = Plugins.ensure_user_plugins_dir()
      assert File.dir?(dir)
    end
  end

  describe "plugin callback registration" do
    test "loading a plugin registers its callbacks" do
      Plugins.load_plugin(CodePuppyControl.Test.TestPlugin)

      # The test plugin registers for :load_prompt
      callbacks = Callbacks.get_callbacks(:load_prompt)
      assert length(callbacks) >= 1
    end

    test "plugin callbacks work correctly" do
      Plugins.load_plugin(CodePuppyControl.Test.TestPlugin)

      result = Callbacks.trigger(:load_prompt)
      assert result =~ "Test Plugin Instructions"
    end
  end

  describe "plugin lifecycle" do
    test "startup callback is invoked on load" do
      # Start agent before loading plugin
      CodePuppyControl.Test.TestPlugin.start_agent()
      CodePuppyControl.Test.TestPlugin.reset_state()

      # Clear callbacks first so we get a fresh registration
      Callbacks.clear()

      # Load plugin - this calls startup/0
      Plugins.load_plugin(CodePuppyControl.Test.TestPlugin)

      # Give the Agent a moment to update
      Process.sleep(10)

      state = CodePuppyControl.Test.TestPlugin.get_state()
      assert state[:startup_called] == true

      CodePuppyControl.Test.TestPlugin.stop_agent()
    end
  end
end
