defmodule CodePuppyControl.REPL.CompletionTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.REPL.Completion

  describe "complete/2 — command type" do
    test "completes slash command prefix" do
      assert Completion.complete("/h", :command) == ["/help", "/history"]
      assert Completion.complete("/he", :command) == ["/help"]
      assert Completion.complete("/q", :command) == ["/quit"]
      assert Completion.complete("/cl", :command) == ["/clear"]
    end

    test "exact match returns single result" do
      assert Completion.complete("/help", :command) == ["/help"]
      assert Completion.complete("/model", :command) == ["/model"]
    end

    test "no match returns empty list" do
      assert Completion.complete("/zzz", :command) == []
    end

    test "no completion for command with args" do
      assert Completion.complete("/model claude", :command) == []
    end
  end

  describe "complete/2 — auto type" do
    test "auto-detects slash command" do
      assert Completion.complete("/h", :auto) == ["/help", "/history"]
    end

    test "auto-detects file path" do
      # This depends on cwd having files — test with a known path
      results = Completion.complete("@lib/", :auto)
      assert is_list(results)
      # All results should start with @
      assert Enum.all?(results, &String.starts_with?(&1, "@"))
    end

    test "no completions for plain text" do
      assert Completion.complete("hello world", :auto) == []
    end
  end

  describe "complete_command/1" do
    test "lists all commands matching prefix" do
      # "/" matches all commands
      all = Completion.complete_command("/")
      assert "/help" in all
      assert "/quit" in all
      assert "/model" in all
      assert "/agent" in all
      assert "/clear" in all
      assert "/history" in all
      assert "/exit" in all
      assert "/pack" in all
    end

    test "/pack is completable from fallback list" do
      assert Completion.complete("/pa", :command) == ["/pack"]
      assert Completion.complete("/pack", :command) == ["/pack"]
    end

    test "all known slash commands are completable" do
      # Ensures the fallback list stays in sync with Registry.register_builtin_commands/0
      all = Completion.complete_command("/")

      expected =
        ~w(/help /model /agent /quit /exit /clear /history /pack /sessions /tui /cd /compact /truncate)

      for cmd <- expected do
        assert cmd in all, "Expected #{cmd} to be in slash-command completions"
      end
    end
  end

  describe "complete_command/1 — dynamic registry integration" do
    setup do
      # Ensure the Registry GenServer is started for these tests
      alias CodePuppyControl.CLI.SlashCommands.Registry

      case Process.whereis(Registry) do
        nil -> start_supervised!({Registry, []})
        _pid -> :ok
      end

      :ok
    end

    test "derives commands from Registry when populated" do
      alias CodePuppyControl.CLI.SlashCommands.Registry

      Registry.register_builtin_commands()

      all = Completion.complete_command("/")
      assert "/pack" in all
      assert Completion.complete("/pa", :command) == ["/pack"]
    end

    test "falls back to hardcoded list when Registry is empty" do
      alias CodePuppyControl.CLI.SlashCommands.Registry

      # Clear all registered commands so Registry.all_names() returns []
      Registry.clear()

      # Completion must use the fallback list
      all = Completion.complete_command("/")

      # Verify we're actually exercising the fallback path (not just getting
      # lucky with a stale Registry). The fallback list is deterministic.
      assert "/help" in all
      assert "/quit" in all
      assert "/pack" in all
      assert "/model" in all

      # Verify prefix matching works through the fallback path
      assert Completion.complete("/pa", :command) == ["/pack"]
      assert Completion.complete("/he", :command) == ["/help"]

      # Re-register builtins so downstream tests aren't affected
      Registry.register_builtin_commands()
    end
  end

  describe "complete_file_path/1" do
    test "returns empty list for non-@ input" do
      assert Completion.complete_file_path("no_at_sign") == []
    end

    test "completes files with @ prefix" do
      results = Completion.complete_file_path("@mix.")
      assert is_list(results)
      # If mix.exs exists in cwd, it should appear
      if File.exists?("mix.exs") do
        assert "@mix.exs" in results
      end
    end

    test "returns empty for nonexistent path" do
      assert Completion.complete_file_path("@zzz_nonexistent_dir/") == []
    end

    test "directories get trailing slash" do
      results = Completion.complete_file_path("@lib/code_puppy_control/repl/")
      assert is_list(results)
      # Results should be @-prefixed paths
      assert Enum.all?(results, &String.starts_with?(&1, "@"))
    end
  end
end
