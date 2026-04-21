defmodule CodePuppyControl.CLI.SlashCommands.RegistryTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Registry}

  # We use async: false because the Registry is a named singleton process
  # with a shared ETS table. We clear between tests for isolation.

  setup do
    # Start the Registry GenServer if not already running
    case Process.whereis(Registry) do
      nil -> start_supervised!({Registry, []})
      _pid -> :ok
    end

    # Clear all commands before each test
    Registry.clear()
    :ok
  end

  describe "register/1" do
    test "registers a command by primary name" do
      cmd = CommandInfo.new(name: "test", description: "A test", handler: fn _, s -> s end)
      assert :ok = Registry.register(cmd)
      assert {:ok, ^cmd} = Registry.get("test")
    end

    test "registers a command with aliases" do
      cmd =
        CommandInfo.new(
          name: "quit",
          description: "Exit",
          handler: fn _, s -> s end,
          aliases: ["exit", "q"]
        )

      assert :ok = Registry.register(cmd)
      assert {:ok, ^cmd} = Registry.get("quit")
      assert {:ok, ^cmd} = Registry.get("exit")
      assert {:ok, ^cmd} = Registry.get("q")
    end

    test "returns error on name conflict for primary name" do
      cmd1 = CommandInfo.new(name: "foo", description: "First", handler: fn _, s -> s end)
      cmd2 = CommandInfo.new(name: "foo", description: "Second", handler: fn _, s -> s end)

      assert :ok = Registry.register(cmd1)
      assert {:error, {:name_conflict, "foo"}} = Registry.register(cmd2)
    end

    test "returns error on name conflict for alias" do
      cmd1 = CommandInfo.new(name: "foo", description: "First", handler: fn _, s -> s end)

      cmd2 =
        CommandInfo.new(
          name: "bar",
          description: "Second",
          handler: fn _, s -> s end,
          aliases: ["foo"]
        )

      assert :ok = Registry.register(cmd1)
      assert {:error, {:name_conflict, "foo"}} = Registry.register(cmd2)
    end

    test "returns error when alias conflicts with existing primary name" do
      cmd1 = CommandInfo.new(name: "foo", description: "First", handler: fn _, s -> s end)

      cmd2 =
        CommandInfo.new(
          name: "bar",
          description: "Second",
          handler: fn _, s -> s end,
          aliases: ["foo"]
        )

      assert :ok = Registry.register(cmd1)
      assert {:error, {:name_conflict, "foo"}} = Registry.register(cmd2)
    end
  end

  describe "get/1" do
    test "returns not_found for unregistered command" do
      assert {:error, :not_found} = Registry.get("nonexistent")
    end

    test "case-insensitive lookup" do
      cmd = CommandInfo.new(name: "Help", description: "Show help", handler: fn _, s -> s end)
      assert :ok = Registry.register(cmd)

      assert {:ok, _} = Registry.get("help")
      assert {:ok, _} = Registry.get("HELP")
      assert {:ok, _} = Registry.get("Help")
    end

    test "exact match wins over case-insensitive match" do
      # Register with lowercase name
      cmd1 = CommandInfo.new(name: "foo", description: "Lowercase", handler: fn _, s -> s end)
      assert :ok = Registry.register(cmd1)

      # Exact match should work
      assert {:ok, found} = Registry.get("foo")
      assert found.name == "foo"
    end

    test "case-insensitive lookup for aliases" do
      cmd =
        CommandInfo.new(
          name: "quit",
          description: "Exit",
          handler: fn _, s -> s end,
          aliases: ["exit"]
        )

      assert :ok = Registry.register(cmd)
      assert {:ok, _} = Registry.get("EXIT")
    end
  end

  describe "list_all/0" do
    test "returns empty list when no commands registered" do
      assert [] = Registry.list_all()
    end

    test "returns unique commands without alias duplicates" do
      cmd1 = CommandInfo.new(name: "quit", description: "Exit", handler: fn _, s -> s end)
      cmd2 = CommandInfo.new(name: "help", description: "Show help", handler: fn _, s -> s end)

      assert :ok = Registry.register(cmd1)
      assert :ok = Registry.register(cmd2)

      all = Registry.list_all()
      assert length(all) == 2
      assert Enum.find(all, &(&1.name == "quit"))
      assert Enum.find(all, &(&1.name == "help"))
    end

    test "deduplicates by primary name even with aliases" do
      cmd =
        CommandInfo.new(
          name: "quit",
          description: "Exit",
          handler: fn _, s -> s end,
          aliases: ["exit", "q"]
        )

      assert :ok = Registry.register(cmd)

      all = Registry.list_all()
      # Only one unique command, even though 3 keys point to it
      assert length(all) == 1
      assert hd(all).name == "quit"
    end
  end

  describe "list_by_category/1" do
    test "filters commands by category" do
      cmd1 =
        CommandInfo.new(name: "help", description: "Help", handler: fn _, s -> s end, category: "core")

      cmd2 =
        CommandInfo.new(
          name: "model",
          description: "Model",
          handler: fn _, s -> s end,
          category: "context"
        )

      assert :ok = Registry.register(cmd1)
      assert :ok = Registry.register(cmd2)

      core = Registry.list_by_category("core")
      assert length(core) == 1
      assert hd(core).name == "help"

      context = Registry.list_by_category("context")
      assert length(context) == 1
      assert hd(context).name == "model"
    end

    test "returns empty list for nonexistent category" do
      assert [] = Registry.list_by_category("nonexistent")
    end
  end

  describe "all_names/0" do
    test "returns all registered names and aliases" do
      cmd =
        CommandInfo.new(
          name: "quit",
          description: "Exit",
          handler: fn _, s -> s end,
          aliases: ["exit", "q"]
        )

      assert :ok = Registry.register(cmd)

      names = Registry.all_names()
      assert "quit" in names
      assert "exit" in names
      assert "q" in names
    end
  end

  describe "clear/0" do
    test "empties the registry" do
      cmd = CommandInfo.new(name: "test", description: "Test", handler: fn _, s -> s end)
      assert :ok = Registry.register(cmd)
      assert {:ok, _} = Registry.get("test")

      assert :ok = Registry.clear()
      assert {:error, :not_found} = Registry.get("test")
      assert [] = Registry.list_all()
    end
  end

  describe "CommandInfo.new/1" do
    test "defaults usage to /<name>" do
      cmd = CommandInfo.new(name: "help", description: "Show help", handler: fn _, s -> s end)
      assert cmd.usage == "/help"
    end

    test "preserves explicit usage" do
      cmd =
        CommandInfo.new(
          name: "model",
          description: "Model",
          handler: fn _, s -> s end,
          usage: "/model <name>"
        )

      assert cmd.usage == "/model <name>"
    end

    test "defaults aliases to empty list" do
      cmd = CommandInfo.new(name: "help", description: "Help", handler: fn _, s -> s end)
      assert cmd.aliases == []
    end

    test "defaults category to core" do
      cmd = CommandInfo.new(name: "help", description: "Help", handler: fn _, s -> s end)
      assert cmd.category == "core"
    end
  end
end
