defmodule Mana.Plugins.CustomCommandsTest do
  use ExUnit.Case, async: false

  alias Mana.Plugins.CustomCommands

  setup do
    # Initialize persistent term with empty commands map
    :persistent_term.put({CustomCommands, :commands}, %{})

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

  describe "default_paths/0" do
    test "returns 6 path entries" do
      paths = CustomCommands.default_paths()
      assert length(paths) == 6

      # Each entry should be a {dir, suffix} tuple
      for {dir, suffix} <- paths do
        assert is_binary(dir)
        assert is_binary(suffix)
      end
    end

    test "includes expected directories in correct precedence order" do
      paths = CustomCommands.default_paths()
      dirs = Enum.map(paths, fn {dir, _suffix} -> dir end)
      suffixes = Enum.map(paths, fn {_dir, suffix} -> suffix end)

      # Check that the expected patterns exist
      assert Enum.any?(dirs, &String.ends_with?(&1, "/commands"))
      assert Enum.any?(dirs, &String.ends_with?(&1, "/prompts"))

      # Check suffixes: 5 .md entries, 1 .prompt.md entry
      md_count = Enum.count(suffixes, &(&1 == ".md"))
      prompt_md_count = Enum.count(suffixes, &(&1 == ".prompt.md"))
      assert md_count == 5
      assert prompt_md_count == 1

      # Last entry should be .github/prompts with .prompt.md suffix
      last = List.last(paths)
      {last_dir, last_suffix} = last
      assert String.ends_with?(last_dir, "/.github/prompts")
      assert last_suffix == ".prompt.md"
    end
  end

  describe "load_commands/1 with custom paths" do
    test "loads commands from temporary directory" do
      tmp_dir = Path.join(System.tmp_dir!(), "mana_test_commands_#{:rand.uniform(999_999)}")
      File.mkdir_p!(tmp_dir)

      test_content = "# Test Command\nThis is a test command for {{args}}"
      File.write!(Path.join(tmp_dir, "test_cmd.md"), test_content)

      # Load from custom path (not the default paths)
      assert :ok = CustomCommands.load_commands([{tmp_dir, ".md"}])

      # Verify the command was loaded
      commands = CustomCommands.loaded_commands()
      command_map = Map.new(commands)
      assert command_map["test_cmd"] == test_content

      # Cleanup
      File.rm_rf!(tmp_dir)
    end

    test "merges commands from multiple directories with precedence" do
      tmp_dir1 = Path.join(System.tmp_dir!(), "mana_test_1_#{:rand.uniform(999_999)}")
      tmp_dir2 = Path.join(System.tmp_dir!(), "mana_test_2_#{:rand.uniform(999_999)}")
      File.mkdir_p!(tmp_dir1)
      File.mkdir_p!(tmp_dir2)

      # Create same command in both directories with different content
      File.write!(Path.join(tmp_dir1, "dup.md"), "from dir1: {{args}}")
      File.write!(Path.join(tmp_dir2, "dup.md"), "from dir2: {{args}}")

      # Load with dir1 first, then dir2 (later wins)
      assert :ok = CustomCommands.load_commands([{tmp_dir1, ".md"}, {tmp_dir2, ".md"}])

      # Later directory should win
      commands = CustomCommands.loaded_commands()
      command_map = Map.new(commands)
      assert command_map["dup"] == "from dir2: {{args}}"

      # Cleanup
      File.rm_rf!(tmp_dir1)
      File.rm_rf!(tmp_dir2)
    end

    test "handles .prompt.md suffix for github prompts" do
      tmp_dir = Path.join(System.tmp_dir!(), "mana_test_prompts_#{:rand.uniform(999_999)}")
      File.mkdir_p!(tmp_dir)

      # Create a .prompt.md file (GitHub Copilot style)
      File.write!(Path.join(tmp_dir, "copilot.prompt.md"), "Copilot prompt: {{args}}")

      # Load with .prompt.md suffix
      assert :ok = CustomCommands.load_commands([{tmp_dir, ".prompt.md"}])

      # Verify command was loaded with correct name (suffix stripped)
      commands = CustomCommands.loaded_commands()
      command_map = Map.new(commands)
      assert command_map["copilot"] == "Copilot prompt: {{args}}"

      # Cleanup
      File.rm_rf!(tmp_dir)
    end

    test "extracts correct name from different suffixes using String.replace_suffix" do
      # This test verifies that we don't strip suffixes multiple times
      # e.g., "test.md.md" with .md suffix should become "test.md", not "test"
      tmp_dir = Path.join(System.tmp_dir!(), "mana_test_suffix_#{:rand.uniform(999_999)}")
      File.mkdir_p!(tmp_dir)

      # Create files that would trigger the trim_trailing bug if we used that
      File.write!(Path.join(tmp_dir, "regular.md"), "regular content")
      File.write!(Path.join(tmp_dir, "double.md.md"), "double md content")
      File.write!(Path.join(tmp_dir, "github.prompt.md"), "github content")

      # Test .md suffix — files should match correctly
      assert :ok = CustomCommands.load_commands([{tmp_dir, ".md"}])
      commands = CustomCommands.loaded_commands()
      command_map = Map.new(commands)

      # Regular .md file
      assert Map.has_key?(command_map, "regular")
      assert command_map["regular"] == "regular content"

      # .md.md file — if we used trim_trailing, this would incorrectly become "double"
      # but with replace_suffix, it correctly becomes "double.md"
      assert Map.has_key?(command_map, "double.md")
      assert command_map["double.md"] == "double md content"

      # .prompt.md file — should NOT match .md suffix
      refute Map.has_key?(command_map, "github")

      # Now test with .prompt.md suffix
      File.write!(Path.join(tmp_dir, "double.prompt.md.prompt.md"), "double prompt content")

      assert :ok = CustomCommands.load_commands([{tmp_dir, ".prompt.md"}])
      commands = CustomCommands.loaded_commands()
      command_map = Map.new(commands)

      # github.prompt.md becomes "github" with .prompt.md suffix
      assert Map.has_key?(command_map, "github")
      assert command_map["github"] == "github content"

      # double.prompt.md.prompt.md becomes "double.prompt.md" (not "double")
      assert Map.has_key?(command_map, "double.prompt.md")
      assert command_map["double.prompt.md"] == "double prompt content"

      # .md file should NOT match .prompt.md suffix
      refute Map.has_key?(command_map, "regular")

      # Cleanup
      File.rm_rf!(tmp_dir)
    end

    test "empty paths list results in no commands" do
      assert :ok = CustomCommands.load_commands([])
      commands = CustomCommands.loaded_commands()
      assert commands == []
    end

    test "gracefully handles non-existent directories" do
      # Should not crash when scanning non-existent directories
      assert :ok = CustomCommands.load_commands([{"/nonexistent/path/xyz", ".md"}])
      commands = CustomCommands.loaded_commands()
      assert commands == []
    end
  end

  describe "loaded_commands/0" do
    test "returns list of commands" do
      # Initialize with empty map
      :persistent_term.put({CustomCommands, :commands}, %{})

      commands = CustomCommands.loaded_commands()
      assert is_list(commands)

      # Cleanup
      :persistent_term.erase({CustomCommands, :commands})
    end

    test "returns commands as {name, content} tuples" do
      :persistent_term.put({CustomCommands, :commands}, %{"test" => "content"})

      commands = CustomCommands.loaded_commands()
      assert {"test", "content"} in commands

      # Cleanup
      :persistent_term.erase({CustomCommands, :commands})
    end
  end

  describe "execute_command/2" do
    setup do
      # Setup test commands in persistent_term as a map
      test_commands = %{
        "greet" => "Hello, {{args}}!",
        "echo" => "You said: {{args}}"
      }

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
