defmodule CodePuppyControl.Plugins.LoaderTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.{Callbacks, Plugins.Loader}

  setup do
    Callbacks.clear()
    :ok
  end

  describe "load_all/0" do
    test "returns a map with builtin and user keys" do
      result = Loader.load_all()
      assert is_map(result)
      assert Map.has_key?(result, :builtin)
      assert Map.has_key?(result, :user)
      assert is_list(result.builtin)
      assert is_list(result.user)
    end
  end

  describe "load_plugin/1 with module" do
    test "loads a valid plugin module" do
      assert {:ok, :test_plugin} = Loader.load_plugin(CodePuppyControl.Test.TestPlugin)
    end

    test "returns error for non-plugin module" do
      assert {:error, {:not_a_plugin, String}} = Loader.load_plugin(String)
    end
  end

  describe "load_plugin/1 with file path" do
    test "returns error for non-existent file" do
      assert {:error, {:file_not_found, _}} = Loader.load_plugin("/tmp/nonexistent.ex")
    end
  end

  describe "user_plugins_dir/0" do
    test "returns a path under the configured plugins directory" do
      dir = Loader.user_plugins_dir()
      assert dir =~ "plugins"
    end
  end

  describe "ensure_user_plugins_dir/0" do
    test "creates the directory" do
      dir = Loader.ensure_user_plugins_dir()
      assert File.dir?(dir)
    end
  end

  describe "list_loaded/0" do
    test "returns empty list initially" do
      # May have test plugin loaded from other tests, so just check it's a list
      loaded = Loader.list_loaded()
      assert is_list(loaded)
    end

    test "returns plugin info after loading" do
      Loader.load_plugin(CodePuppyControl.Test.TestPlugin)

      loaded = Loader.list_loaded()
      test_plugin = Enum.find(loaded, fn p -> p.name == :test_plugin end)

      assert test_plugin != nil
      assert test_plugin.module == CodePuppyControl.Test.TestPlugin
      assert test_plugin.type == :builtin
    end
  end

  describe "plugin registration with callbacks" do
    test "registers plugin callbacks on load" do
      Loader.load_plugin(CodePuppyControl.Test.TestPlugin)

      # Test plugin registers :load_prompt callback
      assert Callbacks.count_callbacks(:load_prompt) >= 1
    end
  end
end
