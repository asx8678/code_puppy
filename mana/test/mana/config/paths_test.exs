defmodule Mana.Config.PathsTest do
  @moduledoc """
  Tests for Mana.Config.Paths module.
  """

  use ExUnit.Case, async: true

  alias Mana.Config.Paths

  describe "config_dir/0" do
    test "returns XDG_CONFIG_HOME/mana when XDG_CONFIG_HOME is set" do
      original = System.get_env("XDG_CONFIG_HOME")
      System.put_env("XDG_CONFIG_HOME", "/tmp/test_xdg_config")

      try do
        assert "/tmp/test_xdg_config/mana" == Paths.config_dir()
      after
        if original, do: System.put_env("XDG_CONFIG_HOME", original), else: System.delete_env("XDG_CONFIG_HOME")
      end
    end

    test "returns ~/.mana when XDG_CONFIG_HOME is not set" do
      original = System.get_env("XDG_CONFIG_HOME")
      System.delete_env("XDG_CONFIG_HOME")
      home = System.get_env("HOME", "")

      try do
        assert Path.join(home, ".mana") == Paths.config_dir()
      after
        if original, do: System.put_env("XDG_CONFIG_HOME", original)
      end
    end
  end

  describe "data_dir/0" do
    test "returns XDG_DATA_HOME/mana when XDG_DATA_HOME is set" do
      original = System.get_env("XDG_DATA_HOME")
      System.put_env("XDG_DATA_HOME", "/tmp/test_xdg_data")

      try do
        assert "/tmp/test_xdg_data/mana" == Paths.data_dir()
      after
        if original, do: System.put_env("XDG_DATA_HOME", original), else: System.delete_env("XDG_DATA_HOME")
      end
    end

    test "returns config_dir/data when XDG_DATA_HOME is not set" do
      original_xdg = System.get_env("XDG_DATA_HOME")
      System.delete_env("XDG_DATA_HOME")
      home = System.get_env("HOME", "")

      try do
        assert Path.join([home, ".mana", "data"]) == Paths.data_dir()
      after
        if original_xdg, do: System.put_env("XDG_DATA_HOME", original_xdg)
      end
    end
  end

  describe "config_file/0" do
    test "returns path to config.json in config directory" do
      home = System.get_env("HOME", "")
      expected = Path.join([home, ".mana", "config.json"])

      assert expected == Paths.config_file()
    end
  end

  describe "models_file/0" do
    test "returns path to models.json in config directory" do
      home = System.get_env("HOME", "")
      expected = Path.join([home, ".mana", "models.json"])

      assert expected == Paths.models_file()
    end
  end

  describe "agents_dir/0" do
    test "returns path to agents subdirectory in data directory" do
      home = System.get_env("HOME", "")
      expected = Path.join([home, ".mana", "data", "agents"])

      assert expected == Paths.agents_dir()
    end
  end

  describe "sessions_dir/0" do
    test "returns path to sessions subdirectory in data directory" do
      home = System.get_env("HOME", "")
      expected = Path.join([home, ".mana", "data", "sessions"])

      assert expected == Paths.sessions_dir()
    end
  end

  describe "ensure_dirs/0" do
    test "creates all directories and returns :ok" do
      # Use a temporary directory for testing
      original_config = System.get_env("XDG_CONFIG_HOME")
      original_data = System.get_env("XDG_DATA_HOME")
      temp_dir = System.tmp_dir!()
      test_config = Path.join(temp_dir, "mana_test_config_#{:erlang.unique_integer([:positive])}")
      test_data = Path.join(temp_dir, "mana_test_data_#{:erlang.unique_integer([:positive])}")

      System.put_env("XDG_CONFIG_HOME", test_config)
      System.put_env("XDG_DATA_HOME", test_data)

      try do
        assert :ok == Paths.ensure_dirs()
        assert File.dir?(Path.join(test_config, "mana"))
        assert File.dir?(Path.join(test_data, "mana"))
        assert File.dir?(Path.join([test_data, "mana", "agents"]))
        assert File.dir?(Path.join([test_data, "mana", "sessions"]))
      after
        # Cleanup
        File.rm_rf!(test_config)
        File.rm_rf!(test_data)

        if original_config,
          do: System.put_env("XDG_CONFIG_HOME", original_config),
          else: System.delete_env("XDG_CONFIG_HOME")

        if original_data, do: System.put_env("XDG_DATA_HOME", original_data), else: System.delete_env("XDG_DATA_HOME")
      end
    end
  end
end
