defmodule Mana.Plugins.PopCommandTest do
  use ExUnit.Case

  alias Mana.Plugins.PopCommand

  setup do
    # Initialize the plugin to set up the stack
    {:ok, _state} = PopCommand.init(%{})
    :ok
  end

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = PopCommand.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(PopCommand, :name, 0)
      assert function_exported?(PopCommand, :init, 1)
      assert function_exported?(PopCommand, :hooks, 0)
      assert function_exported?(PopCommand, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert PopCommand.name() == "pop_command"
    end
  end

  describe "init/1" do
    test "initializes with default config" do
      assert {:ok, state} = PopCommand.init(%{})
      assert state.config == %{}
    end

    test "initializes empty stack" do
      PopCommand.init(%{})
      assert PopCommand.get_stack() == []
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = PopCommand.hooks()
      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :custom_command in hook_names
      assert :custom_command_help in hook_names
    end
  end

  describe "stack management" do
    test "push_selection/1 adds to stack" do
      PopCommand.clear_stack()
      :ok = PopCommand.push_selection(%{agent: "coder", model: "gpt-4o"})
      assert [%{agent: "coder", model: "gpt-4o"}] = PopCommand.get_stack()
    end

    test "push_selection/1 respects max stack size" do
      PopCommand.clear_stack()

      for i <- 1..25 do
        PopCommand.push_selection(%{agent: "agent_#{i}", model: "model_#{i}"})
      end

      stack = PopCommand.get_stack()
      assert length(stack) == 20
    end

    test "pop_selection/0 returns top item" do
      PopCommand.clear_stack()
      PopCommand.push_selection(%{agent: "first", model: "a"})
      PopCommand.push_selection(%{agent: "second", model: "b"})

      assert {:ok, %{agent: "second", model: "b"}} = PopCommand.pop_selection()
      assert [%{agent: "first", model: "a"}] = PopCommand.get_stack()
    end

    test "pop_selection/0 returns :empty on empty stack" do
      PopCommand.clear_stack()
      assert :empty == PopCommand.pop_selection()
    end

    test "get_stack/0 returns current stack" do
      PopCommand.clear_stack()
      assert [] = PopCommand.get_stack()

      PopCommand.push_selection(%{agent: "a", model: "m"})
      assert [_] = PopCommand.get_stack()
    end

    test "clear_stack/0 removes all entries" do
      PopCommand.push_selection(%{agent: "x", model: "y"})
      assert :ok == PopCommand.clear_stack()
      assert [] = PopCommand.get_stack()
    end
  end

  describe "command_help/0" do
    test "returns help entries" do
      entries = PopCommand.command_help()
      assert is_list(entries)
      assert [{"pop", _}] = entries
    end
  end

  describe "handle_command/2" do
    test "returns nil for unknown commands" do
      assert nil == PopCommand.handle_command("/foo", "foo")
    end

    test "handles /pop with empty stack" do
      PopCommand.clear_stack()
      {:ok, text} = PopCommand.handle_command("/pop", "pop")
      assert text =~ "empty"
    end

    test "handles /pop with items on stack" do
      PopCommand.clear_stack()
      PopCommand.push_selection(%{agent: "coder", model: "gpt-4o"})

      {:ok, text} = PopCommand.handle_command("/pop", "pop")
      assert text =~ "Popped"
    end

    test "handles /pop stack subcommand" do
      PopCommand.clear_stack()
      {:ok, text} = PopCommand.handle_command("/pop stack", "pop")
      assert text =~ "stack"
    end

    test "handles /pop clear subcommand" do
      PopCommand.clear_stack()
      PopCommand.push_selection(%{agent: "a", model: "b"})

      {:ok, text} = PopCommand.handle_command("/pop clear", "pop")
      assert text =~ "Cleared"
      assert [] = PopCommand.get_stack()
    end

    test "handles /pop N with count" do
      PopCommand.clear_stack()
      PopCommand.push_selection(%{agent: "a", model: "m1"})
      PopCommand.push_selection(%{agent: "b", model: "m2"})
      PopCommand.push_selection(%{agent: "c", model: "m3"})

      {:ok, text} = PopCommand.handle_command("/pop 2", "pop")
      assert text =~ "2"
      assert [%{agent: "a"}] = PopCommand.get_stack()
    end

    test "handles /pop with invalid count" do
      {:ok, text} = PopCommand.handle_command("/pop abc", "pop")
      assert text =~ "Invalid"
    end

    test "handles /pop with negative count" do
      {:ok, text} = PopCommand.handle_command("/pop -1", "pop")
      assert text =~ "positive"
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert PopCommand.terminate() == :ok
    end
  end
end
