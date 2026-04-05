defmodule Mana.Commands.ColorsTest do
  @moduledoc """
  Tests for Mana.Commands.Colors module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Colors
  alias Mana.Config.Store, as: ConfigStore

  setup do
    # Use temporary directory for tests
    temp_dir = System.tmp_dir!()
    test_config = Path.join(temp_dir, "mana_test_config_#{:erlang.unique_integer([:positive])}")

    original_config = System.get_env("XDG_CONFIG_HOME")
    System.put_env("XDG_CONFIG_HOME", test_config)

    # Start required services
    start_supervised!({ConfigStore, []})

    on_exit(fn ->
      # Cleanup environment
      if original_config,
        do: System.put_env("XDG_CONFIG_HOME", original_config),
        else: System.delete_env("XDG_CONFIG_HOME")

      # Cleanup files
      File.rm_rf!(test_config)
    end)

    :ok
  end

  describe "behaviour implementation" do
    test "implements Mana.Commands.Behaviour" do
      Code.ensure_loaded?(Colors)
      assert function_exported?(Colors, :name, 0)
      assert function_exported?(Colors, :description, 0)
      assert function_exported?(Colors, :usage, 0)
      assert function_exported?(Colors, :execute, 2)
    end

    test "name returns '/colors'" do
      assert Colors.name() == "/colors"
    end

    test "description returns expected string" do
      assert Colors.description() == "Theme/color scheme picker"
    end

    test "usage returns expected string" do
      assert Colors.usage() == "/colors [list|set <theme>|set <banner> <color>|banners|reset]"
    end
  end

  describe "execute/2 - show current colors" do
    test "shows current color settings" do
      assert {:ok, text} = Colors.execute([], %{})
      assert text =~ "Current color scheme"
      assert text =~ "THINKING"
      assert text =~ "SHELL COMMAND"
      assert text =~ "Diff highlighting"
    end
  end

  describe "execute/2 - list themes" do
    test "lists available themes" do
      assert {:ok, text} = Colors.execute(["list"], %{})
      assert text =~ "Available color themes"
      assert text =~ "default"
      assert text =~ "high-contrast"
      assert text =~ "solarized-dark"
      assert text =~ "solarized-light"
    end
  end

  describe "execute/2 - set theme" do
    test "sets valid theme" do
      assert {:ok, text} = Colors.execute(["set", "default"], %{})
      assert text =~ "Switched to theme: default"

      assert ConfigStore.get(:banner_thinking, nil) == "cyan"
    end

    test "returns error for invalid theme" do
      assert {:error, message} = Colors.execute(["set", "invalid-theme"], %{})
      assert message =~ "Unknown theme"
    end
  end

  describe "execute/2 - set banner color" do
    test "sets valid banner color" do
      assert {:ok, text} = Colors.execute(["set", "thinking", "blue"], %{})
      assert text =~ "Set"
      assert text =~ "blue"
    end

    test "returns error for invalid banner" do
      assert {:error, message} = Colors.execute(["set", "invalid_banner", "blue"], %{})
      assert message =~ "Unknown banner"
    end

    test "returns error for invalid color" do
      assert {:error, message} = Colors.execute(["set", "thinking", "invalid_color"], %{})
      assert message =~ "Unknown color"
    end
  end

  describe "execute/2 - list banners" do
    test "shows available banner types" do
      assert {:ok, text} = Colors.execute(["banners"], %{})
      assert text =~ "Available banner types"
      assert text =~ "THINKING"
      assert text =~ "SHELL COMMAND"
      assert text =~ "FILE OPERATION"
    end
  end

  describe "execute/2 - reset" do
    test "resets colors to default" do
      # First set a custom color
      ConfigStore.put(:banner_thinking, "red")

      assert {:ok, text} = Colors.execute(["reset"], %{})
      assert text =~ "Colors reset to default theme"

      # Verify it was reset
      assert ConfigStore.get(:banner_thinking, nil) == "cyan"
    end
  end

  describe "execute/2 - list available colors" do
    test "shows color list" do
      assert {:ok, text} = Colors.execute(["colors"], %{})
      assert text =~ "Basic colors"
      assert text =~ "red"
      assert text =~ "green"
      assert text =~ "blue"
    end
  end

  describe "execute/2 - unknown subcommand" do
    test "returns error for unknown subcommand" do
      assert {:error, message} = Colors.execute(["unknown"], %{})
      assert message =~ "Unknown subcommand: unknown"
    end
  end
end
