defmodule Mana.Plugins.PackParallelismTest do
  use ExUnit.Case, async: false

  alias Mana.Config.Store
  alias Mana.Plugins.PackParallelism

  setup do
    # Use temporary directory for tests
    temp_dir = System.tmp_dir!()
    test_config = Path.join(temp_dir, "mana_test_config_#{:erlang.unique_integer([:positive])}")

    original_config = System.get_env("XDG_CONFIG_HOME")

    System.put_env("XDG_CONFIG_HOME", test_config)

    # Start the store
    start_supervised!(Store)

    on_exit(fn ->
      if original_config,
        do: System.put_env("XDG_CONFIG_HOME", original_config),
        else: System.delete_env("XDG_CONFIG_HOME")

      File.rm_rf!(test_config)
    end)

    :ok
  end

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = PackParallelism.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(PackParallelism, :name, 0)
      assert function_exported?(PackParallelism, :init, 1)
      assert function_exported?(PackParallelism, :hooks, 0)
      assert function_exported?(PackParallelism, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert PackParallelism.name() == "pack_parallelism"
    end
  end

  describe "init/1" do
    test "initializes with default config" do
      assert {:ok, state} = PackParallelism.init(%{})
      assert state.max_parallel == 2
    end

    test "initializes with custom config" do
      config = %{max_parallel: 4}
      assert {:ok, state} = PackParallelism.init(config)
      assert state.max_parallel == 4
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = PackParallelism.hooks()
      assert is_list(hooks)
      assert length(hooks) == 2

      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :load_prompt in hook_names
      assert :custom_command in hook_names
    end
  end

  describe "inject_parallelism_constraint/0" do
    test "injects default max parallel value" do
      # Ensure default config
      Mana.Config.put(:pack_parallelism, nil)

      result = PackParallelism.inject_parallelism_constraint()
      assert result =~ "MAX_PARALLEL_AGENTS = 2"
      assert result =~ "## Pack Parallelism"
    end

    test "injects custom max parallel value" do
      Mana.Config.put(:pack_parallelism, 4)

      result = PackParallelism.inject_parallelism_constraint()
      assert result =~ "MAX_PARALLEL_AGENTS = 4"

      # Cleanup
      Mana.Config.put(:pack_parallelism, nil)
    end
  end

  describe "handle_pack_parallel/2" do
    test "sets parallelism to valid number" do
      result = PackParallelism.handle_pack_parallel("pack-parallel", ["4"])
      assert result == "Pack parallelism set to 4"
      assert PackParallelism.get_max_parallel() == 4

      # Cleanup
      Mana.Config.put(:pack_parallelism, nil)
    end

    test "rejects invalid number" do
      result = PackParallelism.handle_pack_parallel("pack-parallel", ["abc"])
      assert result == "Invalid number. Usage: /pack-parallel N"
    end

    test "rejects negative number" do
      result = PackParallelism.handle_pack_parallel("pack-parallel", ["-1"])
      assert result == "Invalid number. Usage: /pack-parallel N"
    end

    test "rejects zero" do
      result = PackParallelism.handle_pack_parallel("pack-parallel", ["0"])
      assert result == "Invalid number. Usage: /pack-parallel N"
    end

    test "shows usage with no args" do
      result = PackParallelism.handle_pack_parallel("pack-parallel", [])
      assert result =~ "Usage: /pack-parallel N"
      assert result =~ "current:"
    end

    test "returns nil for unknown commands" do
      result = PackParallelism.handle_pack_parallel("other-command", ["4"])
      assert result == nil
    end
  end

  describe "get_max_parallel/0" do
    test "returns default when not configured" do
      Mana.Config.put(:pack_parallelism, nil)
      assert PackParallelism.get_max_parallel() == 2
    end

    test "returns configured value" do
      Mana.Config.put(:pack_parallelism, 8)
      assert PackParallelism.get_max_parallel() == 8

      # Cleanup
      Mana.Config.put(:pack_parallelism, nil)
    end

    test "handles invalid config gracefully" do
      Mana.Config.put(:pack_parallelism, "invalid")
      assert PackParallelism.get_max_parallel() == 2

      # Cleanup
      Mana.Config.put(:pack_parallelism, nil)
    end
  end

  describe "save_max_parallel/1" do
    test "saves valid positive integer" do
      PackParallelism.save_max_parallel(6)
      assert Mana.Config.get(:pack_parallelism) == 6

      # Cleanup
      Mana.Config.put(:pack_parallelism, nil)
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert PackParallelism.terminate() == :ok
    end
  end
end
