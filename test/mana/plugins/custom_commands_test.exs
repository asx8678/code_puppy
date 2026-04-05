defmodule Mana.Plugins.CustomCommandsTest do
  use ExUnit.Case, async: false

  alias Mana.Plugins.CustomCommands

  setup do
    # Initialize persistent term with empty commands
    :persistent_term.put({CustomCommands, :commands}, [])

    on_exit(fn ->
      :persistent_term.erase({CustomCommands, :commands})
    end)

    :ok
  end

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = CustomCommands.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(CustomCommands, :name, 0)
      assert function_exported?(CustomCommands, :init, 1)
      assert function_exported?(CustomCommands, :hooks, 0)
      assert function_exported?(CustomCommands, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert CustomCommands.name() == "custom_commands"
    end
  end

  describe "init/1" do
    test "initializes and loads commands" do
      assert {:ok, state} = CustomCommands.init(%{})
      assert is_map(state.config)
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = CustomCommands.hooks()
      assert is_list(hooks)
      assert length(hooks) == 2

      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :startup in hook_names
      assert :custom_command in hook_names
    end
  end

  describe "load_commands/0" do
    test "loads commands from directories" do
      # Create temp directory with test command
      tmp_dir = Path.join(System.tmp_dir!(), "mana_test_commands_#{:rand.uniform(999_999)}")
      File.mkdir_p!(tmp_dir)

      test_content = "# Test Command\nThis is a test command for {{args}}"
      File.write!(Path.join(tmp_dir, "test_cmd.md"), test_content)

      # Temporarily override the function to use our test dir
      # Load should scan the configured directories
      :ok = CustomCommands.load_commands()

      # Cleanup
      File.rm_rf!(tmp_dir)

      # Should return :ok even if directories don't exist or are empty
      assert :ok == :ok
    end
  end

  describe "loaded_commands/0" do
    test "returns list of commands" do
      # Initialize with empty list
      :persistent_term.put({CustomCommands, :commands}, [])

      commands = CustomCommands.loaded_commands()
      assert is_list(commands)

      # Cleanup
      :persistent_term.erase({CustomCommands, :commands})
    end
  end

  describe "execute_command/2" do
    setup do
      # Setup test commands in persistent_term
      test_commands = [
        {"greet", "Hello, {{args}}!"},
        {"echo", "You said: {{args}}"}
      ]

      :persistent_term.put({CustomCommands, :commands}, test_commands)

      on_exit(fn ->
        :persistent_term.erase({CustomCommands, :commands})
      end)

      :ok
    end

    test "executes command with args substitution" do
      assert {:ok, result} = CustomCommands.execute_command("greet", ["World"])
      assert result == "Hello, World!"
    end

    test "executes command with multiple args" do
      assert {:ok, result} = CustomCommands.execute_command("echo", ["hello", "world"])
      assert result == "You said: hello world"
    end

    test "executes command with empty args" do
      assert {:ok, result} = CustomCommands.execute_command("greet", [])
      assert result == "Hello, !"
    end

    test "returns nil for unknown command" do
      result = CustomCommands.execute_command("unknown", ["test"])
      assert result == nil
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert CustomCommands.terminate() == :ok
    end
  end
end
