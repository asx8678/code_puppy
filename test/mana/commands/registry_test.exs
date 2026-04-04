defmodule Mana.Commands.RegistryTest do
  @moduledoc """
  Tests for Mana.Commands.Registry module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Behaviour
  alias Mana.Commands.Registry

  # Test command module
  defmodule TestCommand do
    @behaviour Behaviour

    @impl true
    def name, do: "/test"

    @impl true
    def description, do: "A test command"

    @impl true
    def usage, do: "/test [args]"

    @impl true
    def execute(args, _context) do
      {:ok, "Executed with: #{inspect(args)}"}
    end
  end

  defmodule AnotherTestCommand do
    @behaviour Behaviour

    @impl true
    def name, do: "/anothertest"

    @impl true
    def description, do: "Another test command"

    @impl true
    def usage, do: "/anothertest"

    @impl true
    def execute(_args, _context) do
      :ok
    end
  end

  defmodule InvalidCommand do
    # Missing required callbacks
    def something, do: :ok
  end

  defmodule NoSlashCommand do
    @behaviour Behaviour

    @impl true
    def name, do: "noslash"

    @impl true
    def description, do: "Invalid - no slash prefix"

    @impl true
    def usage, do: "noslash"

    @impl true
    def execute(_args, _context) do
      :ok
    end
  end

  setup do
    # Start a fresh registry for each test
    start_supervised!({Registry, []})

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer successfully" do
      assert Process.whereis(Registry) != nil
    end

    test "returns correct child_spec" do
      spec = Registry.child_spec([])
      assert spec.id == Registry
      assert spec.type == :worker
      assert spec.restart == :permanent
    end
  end

  describe "register/1" do
    test "registers a valid command module" do
      assert :ok = Registry.register(TestCommand)
    end

    test "returns error for module without behaviour" do
      assert {:error, :invalid_behaviour} = Registry.register(InvalidCommand)
    end

    test "returns error for command without slash prefix" do
      assert {:error, :invalid_name} = Registry.register(NoSlashCommand)
    end

    test "returns error for duplicate registration" do
      assert :ok = Registry.register(TestCommand)
      assert {:error, :already_registered} = Registry.register(TestCommand)
    end
  end

  describe "dispatch/3" do
    test "dispatches to registered command" do
      Registry.register(TestCommand)

      assert {:ok, result} = Registry.dispatch("/test", ["arg1", "arg2"], %{})
      assert result =~ "Executed with"
    end

    test "returns error for unknown command" do
      assert {:error, :unknown_command} = Registry.dispatch("/unknown", [], %{})
    end

    test "handles commands with no args" do
      Registry.register(AnotherTestCommand)

      assert :ok = Registry.dispatch("/anothertest", [], %{})
    end

    test "uses fuzzy matching for close commands" do
      Registry.register(TestCommand)

      # Typo in command name
      assert {:ok, result} = Registry.dispatch("/tset", [], %{})
      assert result =~ "Executed with"
    end

    test "fuzzy matching with distance > 2 returns error" do
      Registry.register(TestCommand)

      # Too different - should not match
      assert {:error, :unknown_command} = Registry.dispatch("/completelywrong", [], %{})
    end

    test "dispatches update stats" do
      Registry.register(TestCommand)
      Registry.dispatch("/test", [], %{})

      stats = Registry.get_stats()
      assert stats.dispatches == 1
      assert stats.errors == 0
    end

    test "dispatch errors update stats" do
      Registry.register(TestCommand)
      Registry.dispatch("/unknown", [], %{})

      stats = Registry.get_stats()
      assert stats.errors == 1
    end
  end

  describe "list_commands/0" do
    test "returns empty list initially" do
      assert Registry.list_commands() == []
    end

    test "returns sorted list of command names" do
      Registry.register(TestCommand)
      Registry.register(AnotherTestCommand)

      commands = Registry.list_commands()
      assert "/anothertest" in commands
      assert "/test" in commands
      assert length(commands) == 2
    end
  end

  describe "get_command/1" do
    test "returns details for registered command" do
      Registry.register(TestCommand)

      assert {:ok, details} = Registry.get_command("/test")
      assert details.name == "/test"
      assert details.description == "A test command"
      assert details.usage == "/test [args]"
      assert details.module == TestCommand
    end

    test "returns error for unknown command" do
      assert {:error, :not_found} = Registry.get_command("/unknown")
    end
  end

  describe "get_stats/0" do
    test "returns initial stats" do
      stats = Registry.get_stats()
      assert stats.commands_registered == 0
      assert stats.dispatches == 0
      assert stats.errors == 0
    end

    test "stats reflect registered commands" do
      Registry.register(TestCommand)
      Registry.register(AnotherTestCommand)

      stats = Registry.get_stats()
      assert stats.commands_registered == 2
    end
  end

  describe "levenshtein distance matching" do
    test "matches exact command" do
      Registry.register(TestCommand)

      assert {:ok, _} = Registry.dispatch("/test", [], %{})
    end

    test "matches with single character difference" do
      Registry.register(TestCommand)

      # Distance 1: deletion /test -> /tst
      assert {:ok, _} = Registry.dispatch("/tst", [], %{})
      # Distance 1: insertion /test -> /tesst
      assert {:ok, _} = Registry.dispatch("/tesst", [], %{})
    end

    test "matches with two character differences" do
      Registry.register(TestCommand)

      # Distance 2: /test -> /tset (two swaps needed)
      assert {:ok, _} = Registry.dispatch("/tset", [], %{})
    end

    test "does not match with distance > 2" do
      Registry.register(TestCommand)

      # Distance > 2
      assert {:error, :unknown_command} = Registry.dispatch("/wrong", [], %{})
    end
  end
end
