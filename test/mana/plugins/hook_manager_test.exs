defmodule Mana.Plugins.HookManagerTest do
  use ExUnit.Case

  alias Mana.Plugins.HookManager

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = HookManager.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(HookManager, :name, 0)
      assert function_exported?(HookManager, :init, 1)
      assert function_exported?(HookManager, :hooks, 0)
      assert function_exported?(HookManager, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert HookManager.name() == "hook_manager"
    end
  end

  describe "init/1" do
    test "initializes with default config" do
      assert {:ok, state} = HookManager.init(%{})
      assert state.config == %{}
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = HookManager.hooks()
      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :custom_command in hook_names
      assert :custom_command_help in hook_names
    end
  end

  describe "command_help/0" do
    test "returns help entries" do
      entries = HookManager.command_help()
      assert is_list(entries)
      assert length(entries) >= 2

      names = Enum.map(entries, fn {name, _desc} -> name end)
      assert "hook" in names
      assert "hooks" in names
    end

    test "entries have name and description" do
      Enum.each(HookManager.command_help(), fn {name, desc} ->
        assert is_binary(name)
        assert is_binary(desc)
      end)
    end
  end

  describe "handle_command/2" do
    test "returns nil for unknown commands" do
      assert nil == HookManager.handle_command("/foo", "foo")
    end

    test "handles /hook command" do
      result = HookManager.handle_command("/hook", "hook")
      assert {:ok, _text} = result
    end

    test "handles /hooks alias" do
      result = HookManager.handle_command("/hooks", "hooks")
      assert {:ok, _text} = result
    end

    test "handles /hook with no args (shows usage)" do
      {:ok, text} = HookManager.handle_command("/hook", "hook")
      assert text =~ "Usage"
    end

    test "handles /hook list subcommand" do
      {:ok, text} = HookManager.handle_command("/hook list", "hook")
      assert is_binary(text)
    end

    test "handles /hook count subcommand" do
      {:ok, text} = HookManager.handle_command("/hook count", "hook")
      assert is_binary(text)
    end

    test "handles unknown subcommand" do
      {:ok, text} = HookManager.handle_command("/hook bogus", "hook")
      assert text =~ "Unknown sub-command"
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert HookManager.terminate() == :ok
    end
  end
end
