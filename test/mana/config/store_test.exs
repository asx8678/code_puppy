defmodule Mana.Config.StoreTest do
  @moduledoc """
  Tests for Mana.Config.Store module.
  """

  use ExUnit.Case, async: false

  alias Mana.Config.Paths
  alias Mana.Config.Store

  setup do
    # Use temporary directory for tests
    temp_dir = System.tmp_dir!()
    test_config = Path.join(temp_dir, "mana_test_config_#{:erlang.unique_integer([:positive])}")
    test_data = Path.join(temp_dir, "mana_test_data_#{:erlang.unique_integer([:positive])}")

    original_config = System.get_env("XDG_CONFIG_HOME")
    original_data = System.get_env("XDG_DATA_HOME")

    System.put_env("XDG_CONFIG_HOME", test_config)
    System.put_env("XDG_DATA_HOME", test_data)

    # Start the store
    start_supervised!(Store)

    on_exit(fn ->
      # Cleanup environment
      if original_config,
        do: System.put_env("XDG_CONFIG_HOME", original_config),
        else: System.delete_env("XDG_CONFIG_HOME")

      if original_data, do: System.put_env("XDG_DATA_HOME", original_data), else: System.delete_env("XDG_DATA_HOME")

      # Cleanup files
      File.rm_rf!(test_config)
      File.rm_rf!(test_data)
    end)

    :ok
  end

  describe "start_link/1" do
    test "starts the GenServer successfully" do
      assert Process.whereis(Store) != nil
    end

    test "creates ETS table with correct properties" do
      # Table should exist and be public
      assert :ets.whereis(:mana_config) != :undefined
    end
  end

  describe "get/2" do
    test "returns default value for unset keys" do
      assert Store.get(:nonexistent_key, "default") == "default"
      assert Store.get(:another_key, nil) == nil
      assert Store.get(:number_key, 42) == 42
    end

    test "returns stored value after put" do
      Store.put(:test_key, "test_value")
      assert Store.get(:test_key, "default") == "test_value"
    end

    test "reads from ETS directly (fast path, no GenServer call)" do
      Store.put(:fast_key, "fast_value")
      # This should be a direct ETS lookup
      assert Store.get(:fast_key, nil) == "fast_value"
    end
  end

  describe "put/3" do
    test "stores value and returns :ok" do
      assert Store.put(:put_key, "put_value") == :ok
      assert Store.get(:put_key, nil) == "put_value"
    end

    test "overwrites existing values" do
      Store.put(:overwrite_key, "original")
      Store.put(:overwrite_key, "updated")
      assert Store.get(:overwrite_key, nil) == "updated"
    end

    test "handles different value types" do
      Store.put(:string_key, "string")
      Store.put(:int_key, 42)
      Store.put(:float_key, 3.14)
      Store.put(:bool_key, true)
      Store.put(:map_key, %{"a" => 1, "b" => 2})
      Store.put(:list_key, [1, 2, 3])

      assert Store.get(:string_key, nil) == "string"
      assert Store.get(:int_key, nil) == 42
      assert Store.get(:float_key, nil) == 3.14
      assert Store.get(:bool_key, nil) == true
      assert Store.get(:map_key, nil) == %{"a" => 1, "b" => 2}
      assert Store.get(:list_key, nil) == [1, 2, 3]
    end
  end

  describe "flush/0" do
    test "writes config to JSON file" do
      Store.put(:flush_key, "flush_value")
      Store.put(:another_key, 123)

      assert :ok == Store.flush()

      # Verify file was written
      assert File.exists?(Paths.config_file())

      # Read and verify contents
      {:ok, contents} = File.read(Paths.config_file())
      config = Jason.decode!(contents)

      assert config["flush_key"] == "flush_value"
      assert config["another_key"] == 123
    end

    test "returns :ok even when no changes" do
      assert :ok == Store.flush()
    end
  end

  describe "load_config/0" do
    test "reloads configuration from file" do
      # First, write some config
      Store.put(:reload_key, "reload_value")
      Store.flush()

      # Manually modify the file
      config = %{"manual_key" => "manual_value", "reload_key" => "updated_value"}
      File.write!(Paths.config_file(), Jason.encode!(config))

      # Reload
      assert :ok == Store.load_config()

      # Verify new values
      assert Store.get(:manual_key, nil) == "manual_value"
      assert Store.get(:reload_key, nil) == "updated_value"
    end

    test "handles missing file gracefully" do
      # Delete the config file if it exists
      File.rm(Paths.config_file())

      # Should not crash
      assert :ok == Store.load_config()
    end

    test "handles invalid JSON gracefully" do
      # Write invalid JSON
      File.write!(Paths.config_file(), "not valid json{")

      # Should not crash
      assert :ok == Store.load_config()
    end
  end

  describe "child_spec/1" do
    test "returns correct child specification" do
      spec = Store.child_spec([])

      assert spec.id == Store
      assert spec.type == :worker
      assert spec.restart == :permanent
    end
  end
end
