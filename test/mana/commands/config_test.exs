defmodule Mana.Commands.ConfigTest do
  @moduledoc """
  Tests for Mana.Commands.Config module.
  """

  use ExUnit.Case, async: false

  alias Mana.Commands.Config
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
      Code.ensure_loaded?(Config)
      assert function_exported?(Config, :name, 0)
      assert function_exported?(Config, :description, 0)
      assert function_exported?(Config, :usage, 0)
      assert function_exported?(Config, :execute, 2)
    end

    test "name returns '/config'" do
      assert Config.name() == "/config"
    end

    test "description returns expected string" do
      assert Config.description() == "View and edit Mana configuration"
    end

    test "usage returns expected string" do
      assert Config.usage() == "/config [get <key>|set <key> <value>|delete <key>|keys]"
    end
  end

  describe "execute/2 - show all config" do
    test "shows message when no config set" do
      assert {:ok, text} = Config.execute([], %{})
      assert text =~ "No configuration set"
    end

    test "shows all config values" do
      ConfigStore.put(:test_key, "test_value")
      ConfigStore.put(:another_key, 42)

      assert {:ok, text} = Config.execute([], %{})
      assert text =~ "test_key"
      assert text =~ "test_value"
      assert text =~ "another_key"
    end
  end

  describe "execute/2 - get config value" do
    test "gets existing config value" do
      ConfigStore.put(:my_setting, "my_value")

      assert {:ok, "my_setting = \"my_value\""} = Config.execute(["get", "my_setting"], %{})
    end

    test "shows not set for unset key" do
      assert {:ok, message} = Config.execute(["get", "unset_key_xyz"], %{})
      assert message =~ "unset_key_xyz"
      assert message =~ "not set" or message =~ "Unknown key"
    end
  end

  describe "execute/2 - set config value" do
    test "sets string value" do
      assert {:ok, text} = Config.execute(["set", "new_key", "new_value"], %{})
      assert text =~ "Set new_key"
      assert text =~ "new_value"

      assert ConfigStore.get(:new_key, nil) == "new_value"
    end

    test "parses boolean values" do
      assert {:ok, _} = Config.execute(["set", "bool_true", "true"], %{})
      assert ConfigStore.get(:bool_true, nil) == true

      assert {:ok, _} = Config.execute(["set", "bool_false", "false"], %{})
      assert ConfigStore.get(:bool_false, nil) == false
    end

    test "parses integer values" do
      assert {:ok, _} = Config.execute(["set", "int_key", "42"], %{})
      assert ConfigStore.get(:int_key, nil) == 42
    end

    test "parses float values" do
      assert {:ok, _} = Config.execute(["set", "float_key", "3.14"], %{})
      assert ConfigStore.get(:float_key, nil) == 3.14
    end

    test "set with multi-word value" do
      assert {:ok, _} = Config.execute(["set", "multi", "this", "is", "a", "test"], %{})
      assert ConfigStore.get(:multi, nil) == "this is a test"
    end

    test "returns error for missing value" do
      assert {:error, "Usage: /config set <key> <value>"} =
               Config.execute(["set", "key_only"], %{})
    end
  end

  describe "execute/2 - delete config value" do
    test "deletes existing config value" do
      ConfigStore.put(:to_delete, "value")

      assert {:ok, "Deleted: to_delete"} = Config.execute(["delete", "to_delete"], %{})
    end
  end

  describe "execute/2 - list keys" do
    test "lists available config keys" do
      assert {:ok, text} = Config.execute(["keys"], %{})
      assert text =~ "Available configuration keys"
      assert text =~ "current_model"
      assert text =~ "theme"
      assert text =~ "color_scheme"
    end
  end

  describe "execute/2 - unknown subcommand" do
    test "returns error for unknown subcommand" do
      assert {:error, message} = Config.execute(["unknown"], %{})
      assert message =~ "Unknown subcommand: unknown"
    end
  end
end
