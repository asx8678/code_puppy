defmodule Mana.TUI.CompletionTest do
  @moduledoc """
  Tests for Mana.TUI.Completion module.
  """

  use ExUnit.Case, async: false

  alias Mana.TUI.Completion
  alias Mana.Commands.Registry, as: CommandRegistry

  @project_root File.cwd!()

  setup do
    # Ensure we're in the project root for file completion tests
    # (other tests may change the CWD)
    File.cd!(@project_root)

    # Ensure CommandRegistry is started for command completion
    start_supervised!({Mana.Config.Store, []})
    start_supervised!(CommandRegistry)

    # Register some known commands for completion testing
    # Mana.Commands.Core contains nested modules (Help, Exit, etc.)
    CommandRegistry.register(Mana.Commands.Core.Help)
    CommandRegistry.register(Mana.Commands.Core.Exit)
    CommandRegistry.register(Mana.Commands.Model)
    CommandRegistry.register(Mana.Commands.Pack)
    CommandRegistry.register(Mana.Commands.Skills)
    CommandRegistry.register(Mana.Commands.Agent)
    CommandRegistry.register(Mana.Commands.Scheduler)
    CommandRegistry.register(Mana.Commands.Config)

    on_exit(fn ->
      File.cd!(@project_root)
    end)

    :ok
  end

  describe "complete/2 — empty input" do
    test "returns empty completions for empty string" do
      assert {[], ""} = Completion.complete("")
    end
  end

  describe "complete/2 — command completion ( / prefix )" do
    test "completes commands starting with /m" do
      {completions, _prefix} = Completion.complete("/m", %{})

      # Should include /model at minimum
      assert Enum.any?(completions, &String.starts_with?(&1, "/model"))
    end

    test "completes /pack command" do
      {completions, _prefix} = Completion.complete("/pack", %{})

      assert Enum.any?(completions, &(&1 == "/pack"))
    end

    test "completions are sorted" do
      {completions, _prefix} = Completion.complete("/", %{})

      assert completions == Enum.sort(completions)
    end

    test "narrows down as prefix grows" do
      {broad, _} = Completion.complete("/", %{})
      {narrow, _} = Completion.complete("/sk", %{})

      assert length(narrow) <= length(broad)
    end

    test "returns empty list for non-matching prefix" do
      {completions, _prefix} = Completion.complete("/xyzzy_no_such_command", %{})

      assert completions == []
    end

    test "completes command with argument — /model" do
      {completions, _prefix} = Completion.complete("/model ", %{})

      # Should try to match agents for /model argument
      assert is_list(completions)
    end
  end

  describe "complete/2 — file path completion" do
    test "completes files in current directory" do
      {completions, _prefix} = Completion.complete("mix", %{})

      # mix.exs should be in the project root
      assert Enum.any?(completions, &String.contains?(&1, "mix"))
    end

    test "returns empty for nonexistent paths" do
      {completions, _prefix} = Completion.complete("/no/such/path/xyz", %{})

      assert completions == []
    end

    test "completes directories with trailing slash" do
      {completions, _prefix} = Completion.complete("li", %{})

      # lib/ should be in the project
      assert Enum.any?(completions, &String.ends_with?(&1, "lib/"))
    end
  end

  describe "longest_common_prefix/2" do
    test "returns empty string for empty list" do
      assert Completion.longest_common_prefix([], "") == ""
    end

    test "returns single item as prefix" do
      assert Completion.longest_common_prefix(["/model"], "/m") == "/model"
    end

    test "finds common prefix across multiple strings" do
      result = Completion.longest_common_prefix(["/model", "/model"], "/m")
      assert result == "/model"
    end

    test "never returns shorter than original" do
      result =
        Completion.longest_common_prefix(["/abc", "/def"], "/a")

      # Common prefix is "/" which is shorter than "/a", so return "/a"
      assert String.length(result) >= String.length("/a")
    end
  end

  describe "cycle/2" do
    test "returns {0, \"\"} for empty list" do
      assert Completion.cycle(0, []) == {0, ""}
    end

    test "cycles to next item" do
      assert {1, "b"} = Completion.cycle(0, ["a", "b", "c"])
    end

    test "wraps around" do
      assert {0, "a"} = Completion.cycle(2, ["a", "b", "c"])
    end

    test "cycles through items" do
      items = ["x", "y", "z"]

      {i1, v1} = Completion.cycle(0, items)
      assert i1 == 1 and v1 == "y"

      {i2, v2} = Completion.cycle(i1, items)
      assert i2 == 2 and v2 == "z"

      {i3, v3} = Completion.cycle(i2, items)
      assert i3 == 0 and v3 == "x"
    end

    test "single item cycles back to itself" do
      assert {0, "only"} = Completion.cycle(0, ["only"])
    end
  end
end
