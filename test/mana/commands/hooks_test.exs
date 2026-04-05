defmodule Mana.Commands.HooksTest do
  @moduledoc """
  Tests for Mana.Commands.Hooks module.
  """

  use ExUnit.Case, async: false

  alias Mana.Callbacks.Registry, as: CallbacksRegistry
  alias Mana.Commands.Hooks

  setup do
    # Start required services
    start_supervised!({CallbacksRegistry, []})

    :ok
  end

  describe "behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      Code.ensure_loaded?(Hooks)
      assert function_exported?(Hooks, :name, 0)
      assert function_exported?(Hooks, :description, 0)
      assert function_exported?(Hooks, :usage, 0)
      assert function_exported?(Hooks, :execute, 2)
    end

    test "name returns '/hooks'" do
      assert Hooks.name() == "/hooks"
    end

    test "description returns expected string" do
      assert Hooks.description() == "List and manage TTSR/callback hooks"
    end

    test "usage returns expected string" do
      assert Hooks.usage() == "/hooks [list|status|phases]"
    end
  end

  describe "execute/2 - usage" do
    test "shows usage when called with no args" do
      assert {:ok, text} = Hooks.execute([], %{})
      assert text =~ "Hook management commands"
      assert text =~ "list"
      assert text =~ "status"
      assert text =~ "phases"
    end
  end

  describe "execute/2 - list" do
    test "shows message when no callbacks registered" do
      assert {:ok, text} = Hooks.execute(["list"], %{})
      assert text =~ "No callbacks registered"
    end

    test "lists registered callbacks" do
      # Register a test callback
      test_fn = fn -> :ok end
      :ok = CallbacksRegistry.register(:startup, test_fn)

      assert {:ok, text} = Hooks.execute(["list"], %{})
      assert text =~ "startup"
    end
  end

  describe "execute/2 - status" do
    test "shows status when no callbacks" do
      assert {:ok, text} = Hooks.execute(["status"], %{})
      assert text =~ "No callbacks registered"
    end

    test "shows callback counts per phase" do
      # Register a test callback
      test_fn = fn -> :ok end
      :ok = CallbacksRegistry.register(:startup, test_fn)

      assert {:ok, text} = Hooks.execute(["status"], %{})
      assert text =~ "startup"
      assert text =~ "Callback status"
    end
  end

  describe "execute/2 - phases" do
    test "lists all available hook phases" do
      assert {:ok, text} = Hooks.execute(["phases"], %{})
      assert text =~ "Available hook phases"
      assert text =~ "startup"
      assert text =~ "invoke_agent"
      assert text =~ "agent_run_end"
    end
  end

  describe "execute/2 - unknown subcommand" do
    test "returns error for unknown subcommand" do
      assert {:error, message} = Hooks.execute(["unknown"], %{})
      assert message =~ "Unknown subcommand: unknown"
    end
  end
end
