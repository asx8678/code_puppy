defmodule Mana.Plugins.SyntheticStatusTest do
  @moduledoc """
  Tests for the `synthetic_status` plugin.
  """

  use ExUnit.Case, async: false

  alias Mana.Plugins.SyntheticStatus

  describe "behaviour implementation" do
    test "implements Mana.Plugin.Behaviour callbacks" do
      Code.ensure_loaded(SyntheticStatus)

      assert function_exported?(SyntheticStatus, :name, 0)
      assert function_exported?(SyntheticStatus, :init, 1)
      assert function_exported?(SyntheticStatus, :hooks, 0)
      assert function_exported?(SyntheticStatus, :terminate, 0)
    end

    test "name returns 'synthetic_status'" do
      assert SyntheticStatus.name() == "synthetic_status"
    end
  end

  describe "init/1" do
    test "returns ok with default config" do
      assert {:ok, state} = SyntheticStatus.init(%{})
      assert is_map(state)
    end

    test "stores config in state" do
      config = %{extra: "value"}
      assert {:ok, state} = SyntheticStatus.init(config)
      assert state.config == config
    end
  end

  describe "hooks/0" do
    test "returns custom_command and custom_command_help hooks" do
      hooks = SyntheticStatus.hooks()

      phases = Enum.map(hooks, fn {phase, _} -> phase end)

      assert :custom_command in phases
      assert :custom_command_help in phases
    end

    test "all hook functions are callable" do
      hooks = SyntheticStatus.hooks()

      for {_phase, func} <- hooks do
        assert is_function(func)
      end
    end
  end

  describe "command_help/0" do
    test "returns help entries for both command names" do
      help = SyntheticStatus.command_help()

      assert is_list(help)
      names = Enum.map(help, fn {name, _} -> name end)
      assert "synthetic_status" in names
      assert "status" in names
    end

    test "each entry has a name and description" do
      help = SyntheticStatus.command_help()

      for {name, desc} <- help do
        assert is_binary(name)
        assert is_binary(desc)
      end
    end
  end

  describe "handle_command/2" do
    test "handles 'synthetic_status' command name" do
      assert {:ok, result} = SyntheticStatus.handle_command("/synthetic_status", "synthetic_status")
      assert is_binary(result)
      assert result =~ "System Status"
      assert result =~ "Status:"
    end

    test "handles 'status' alias" do
      assert {:ok, result} = SyntheticStatus.handle_command("/status", "status")
      assert is_binary(result)
      assert result =~ "System Status"
    end

    test "returns nil for unhandled command names" do
      assert SyntheticStatus.handle_command("/foo", "foo") == nil
    end

    test "result includes version" do
      {:ok, result} = SyntheticStatus.handle_command("/status", "status")
      assert result =~ "Version:"
      assert result =~ Mana.version()
    end

    test "result includes children count" do
      {:ok, result} = SyntheticStatus.handle_command("/status", "status")
      assert result =~ "Children:"
    end
  end

  describe "format_status/1" do
    test "formats health info map into terminal string" do
      info = %{status: "healthy", children: 5, version: "0.1.0"}
      output = SyntheticStatus.format_status(info)

      assert output =~ "System Status"
      assert output =~ "Status:   healthy"
      assert output =~ "Children: 5"
      assert output =~ "Version:  0.1.0"
    end

    test "handles degraded status" do
      info = %{status: "degraded", children: 0, version: "0.1.0"}
      output = SyntheticStatus.format_status(info)

      assert output =~ "Status:   degraded"
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert SyntheticStatus.terminate() == :ok
    end
  end
end
