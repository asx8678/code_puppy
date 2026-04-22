defmodule CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistenceTest do
  @moduledoc """
  Tests for AddModelPersistence: persist, read_existing, atomic_write_json,
  and concurrency safety.

  Split from add_model_test.exs to keep under the 600-line cap.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistence

  setup do
    # Start the LockKeeper for concurrency-safe persistence
    case Process.whereis(AddModelPersistence.LockKeeper) do
      nil -> start_supervised!({AddModelPersistence.LockKeeper, []})
      _pid -> :ok
    end

    # Use a temp directory for extra_models.json
    tmp_dir = Path.join(System.tmp_dir!(), "cp_add_model_persist_test_#{:erlang.unique_integer([:positive])}")
    File.mkdir_p!(tmp_dir)

    original_env = System.get_env("PUP_EX_HOME")
    System.put_env("PUP_EX_HOME", tmp_dir)

    on_exit(fn ->
      if original_env do
        System.put_env("PUP_EX_HOME", original_env)
      else
        System.delete_env("PUP_EX_HOME")
      end

      File.rm_rf!(tmp_dir)
    end)

    {:ok, tmp_dir: tmp_dir}
  end

  # ── AddModelPersistence.persist/2 ────────────────────────────────────────

  describe "persist/2" do
    test "creates new extra_models.json with model config", %{tmp_dir: tmp_dir} do
      config = %{"type" => "openai", "name" => "gpt-5", "provider" => "openai"}

      result = AddModelPersistence.persist("openai-gpt-5", config)

      assert {:ok, "openai-gpt-5"} = result

      path = Path.join(tmp_dir, "extra_models.json")
      assert File.exists?(path)

      {:ok, data} = Jason.decode(File.read!(path))
      assert data["openai-gpt-5"]["type"] == "openai"
    end

    test "merges into existing extra_models.json", %{tmp_dir: tmp_dir} do
      config_a = %{"type" => "openai", "name" => "gpt-5", "provider" => "openai"}
      config_b = %{"type" => "anthropic", "name" => "claude-3", "provider" => "anthropic"}

      {:ok, _} = AddModelPersistence.persist("openai-gpt-5", config_a)
      {:ok, _} = AddModelPersistence.persist("anthropic-claude-3", config_b)

      path = Path.join(tmp_dir, "extra_models.json")
      {:ok, data} = Jason.decode(File.read!(path))
      assert map_size(data) == 2
      assert data["anthropic-claude-3"]["type"] == "anthropic"
    end

    test "rejects duplicate model key", %{tmp_dir: _tmp_dir} do
      config = %{"type" => "openai", "name" => "gpt-5"}
      :ok = AddModelPersistence.persist("openai-gpt-5", config) |> ok_or_dup()

      result = AddModelPersistence.persist("openai-gpt-5", %{"type" => "openai", "name" => "gpt-5-v2"})
      assert result == {:error, :already_exists}
    end

    test "allows adding second model after first", %{tmp_dir: tmp_dir} do
      :ok = AddModelPersistence.persist("openai-gpt-5", %{"type" => "openai"}) |> ok_or_dup()
      {:ok, key} = AddModelPersistence.persist("anthropic-claude-3", %{"type" => "anthropic"})
      assert key == "anthropic-claude-3"

      path = Path.join(tmp_dir, "extra_models.json")
      {:ok, data} = Jason.decode(File.read!(path))
      assert map_size(data) == 2
    end
  end

  # ── read_existing/1 ─────────────────────────────────────────────────────

  describe "read_existing/1" do
    test "returns empty map for nonexistent file" do
      {:ok, data} = AddModelPersistence.read_existing("/tmp/nonexistent_cp_test_#{:erlang.unique_integer([:positive])}.json")
      assert data == %{}
    end

    test "reads existing file correctly", %{tmp_dir: tmp_dir} do
      path = Path.join(tmp_dir, "extra_models.json")
      data = %{"test-key" => %{"type" => "openai"}}
      File.mkdir_p!(tmp_dir)
      File.write!(path, Jason.encode!(data))

      {:ok, loaded} = AddModelPersistence.read_existing(path)
      assert loaded["test-key"]["type"] == "openai"
    end
  end

  # ── atomic_write_json/2 ────────────────────────────────────────────────

  describe "atomic_write_json/2" do
    test "writes valid JSON", %{tmp_dir: tmp_dir} do
      path = Path.join(tmp_dir, "test_write.json")
      data = %{"model-a" => %{"type" => "openai", "name" => "gpt-5"}}
      {:ok, _path} = AddModelPersistence.atomic_write_json(path, data)

      {:ok, decoded} = Jason.decode(File.read!(path))
      assert decoded == data
    end

    test "creates parent directories" do
      deep_path = Path.join([System.tmp_dir!(), "cp_add_model_deep_#{:erlang.unique_integer([:positive])}", "sub", "extra_models.json"])

      on_exit(fn ->
        dir = Path.dirname(Path.dirname(deep_path))
        File.rm_rf!(dir)
      end)

      {:ok, _path} = AddModelPersistence.atomic_write_json(deep_path, %{"test" => %{"type" => "openai"}})
      assert File.exists?(deep_path)
    end

    test "temp file is written in the target directory (no :exdev risk)" do
      uniq = :erlang.unique_integer([:positive])
      dir = Path.join(System.tmp_dir!(), "cp_add_model_adjacent_#{uniq}")
      File.mkdir_p!(dir)

      on_exit(fn ->
        File.rm_rf!(dir)
      end)

      path = Path.join(dir, "extra_models.json")
      data = %{"test-model" => %{"type" => "openai"}}
      {:ok, ^path} = AddModelPersistence.atomic_write_json(path, data)

      # No leftover temp files in the directory — rename succeeded, so
      # no orphaned .cp_extra_models_*.tmp should remain.
      tmp_files =
        File.ls!(dir)
        |> Enum.filter(&String.starts_with?(&1, ".cp_extra_models_"))

      assert tmp_files == [], "orphan temp files found: #{inspect(tmp_files)}"
    end

    test "cleans up temp file on write failure", %{tmp_dir: tmp_dir} do
      # Create a directory where the *file* already exists as a directory,
      # so the write to the temp path inside it will succeed but the rename
      # will fail because the target is a directory.
      path = Path.join(tmp_dir, "blocked_write.json")
      File.mkdir_p!(path)

      result = AddModelPersistence.atomic_write_json(path, %{"x" => 1})

      assert match?({:error, _}, result)

      # No orphaned .tmp files in tmp_dir
      tmp_files =
        File.ls!(tmp_dir)
        |> Enum.filter(&String.starts_with?(&1, ".cp_extra_models_"))

      assert tmp_files == [], "orphan temp files after error: #{inspect(tmp_files)}"
    after
      File.rm_rf!(path)
    end

    test "overwrites existing file atomically", %{tmp_dir: tmp_dir} do
      path = Path.join(tmp_dir, "overwrite_test.json")

      # First write
      {:ok, ^path} = AddModelPersistence.atomic_write_json(path, %{"v" => 1})
      {:ok, d1} = Jason.decode(File.read!(path))
      assert d1 == %{"v" => 1}

      # Second write — should replace, not merge or corrupt
      {:ok, ^path} = AddModelPersistence.atomic_write_json(path, %{"v" => 2, "extra" => true})
      {:ok, d2} = Jason.decode(File.read!(path))
      assert d2 == %{"v" => 2, "extra" => true}
    end

    test "returns {:error, _} instead of crashing on real File.Error (mkdir)", %{tmp_dir: tmp_dir} do
      readonly_dir = Path.join(tmp_dir, "readonly_#{:erlang.unique_integer([:positive])}")
      File.mkdir_p!(readonly_dir)
      File.chmod!(readonly_dir, 0o444)

      on_exit(fn ->
        File.chmod!(readonly_dir, 0o755)
      end)

      nested_path = Path.join([readonly_dir, "sub", "deep", "extra_models.json"])
      result = AddModelPersistence.atomic_write_json(nested_path, %{"test" => 1})

      assert {:error, _reason} = result

      tmp_files =
        File.ls!(readonly_dir)
        |> Enum.filter(&String.starts_with?(&1, ".cp_extra_models_"))

      assert tmp_files == [], "orphan temp files after mkdir error: #{inspect(tmp_files)}"
    after
      File.chmod!(readonly_dir, 0o755)
      File.rm_rf!(readonly_dir)
    end

    test "returns {:error, _} instead of crashing on real File.Error (write)", %{tmp_dir: tmp_dir} do
      target = Path.join(tmp_dir, "is_a_dir_not_a_file.json")
      File.mkdir_p!(target)

      result = AddModelPersistence.atomic_write_json(target, %{"x" => 1})
      assert {:error, _reason} = result

      tmp_files =
        File.ls!(tmp_dir)
        |> Enum.filter(&String.starts_with?(&1, ".cp_extra_models_"))

      assert tmp_files == [], "orphan temp files after write error: #{inspect(tmp_files)}"
    after
      File.rm_rf!(target)
    end

    test "rename failure returns {:error, _} tuple (not MatchError)", %{tmp_dir: tmp_dir} do
      # Force a rename failure by making the target a directory.
      # The tmp file write will succeed, but File.rename/2 will fail
      # because the target path is a directory.
      target = Path.join(tmp_dir, "rename_target_is_dir.json")
      File.mkdir_p!(target)

      result = AddModelPersistence.atomic_write_json(target, %{"rename" => "test"})

      # Must return an error tuple, not raise MatchError
      assert {:error, reason} = result
      assert is_binary(reason) or reason != nil

      # No orphan temp files
      tmp_files =
        File.ls!(tmp_dir)
        |> Enum.filter(&String.starts_with?(&1, ".cp_extra_models_"))

      assert tmp_files == [], "orphan temp files after rename error: #{inspect(tmp_files)}"
    after
      File.rm_rf!(target)
    end
  end

  # ── Concurrency safety ─────────────────────────────────────────────────

  describe "concurrent persistence" do
    test "no lost updates when multiple persists run concurrently", %{tmp_dir: tmp_dir} do
      # Ensure LockKeeper is running
      case Process.whereis(AddModelPersistence.LockKeeper) do
        nil -> start_supervised!({AddModelPersistence.LockKeeper, []})
        _pid -> :ok
      end

      tasks =
        for i <- 1..20 do
          Task.async(fn ->
            key = "model-#{i}"
            config = %{"type" => "openai", "name" => "model-#{i}"}
            AddModelPersistence.persist(key, config)
          end)
        end

      results = Task.await_many(tasks, 15_000)

      successes = Enum.count(results, fn r -> match?({:ok, _}, r) end)
      assert successes == 20

      path = Path.join(tmp_dir, "extra_models.json")
      {:ok, data} = Jason.decode(File.read!(path))
      assert map_size(data) == 20
    end
  end

  # ── Helpers ──────────────────────────────────────────────────────────────

  defp ok_or_dup({:ok, _key}), do: :ok
  defp ok_or_dup({:error, :already_exists}), do: :ok
  defp ok_or_dup(other), do: other
end
