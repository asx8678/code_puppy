defmodule CodePuppyControl.Config.ModelsTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Config.{Loader, Models, Writer}

  @tmp_dir System.tmp_dir!()
  @test_cfg Path.join(@tmp_dir, "models_test_#{:erlang.unique_integer([:positive])}.cfg")

  setup do
    File.write!(@test_cfg, "[puppy]\nmodel = test-model\n")
    Loader.load(@test_cfg)

    on_exit(fn ->
      File.rm(@test_cfg)
      Loader.invalidate()
    end)

    :ok
  end

  describe "global_model_name/0" do
    test "returns configured model" do
      assert Models.global_model_name() == "test-model"
    end

    test "falls back to default when not set" do
      File.write!(@test_cfg, "[puppy]\n")
      Loader.load(@test_cfg)

      assert Models.global_model_name() == Models.default_model()
    end

    test "puppy.cfg model wins over registry model" do
      # Even if registry is running, explicit config should win
      assert Models.global_model_name() == "test-model"
    end
  end

  describe "default_model/0" do
    test "returns gpt-5 when ModelRegistry is not running" do
      # Stop the registry temporarily to verify graceful fallback
      original_pid = GenServer.whereis(CodePuppyControl.ModelRegistry)

      if original_pid do
        # Stop it — ETS table gets destroyed with the owner process
        GenServer.stop(CodePuppyControl.ModelRegistry, :shutdown)
        assert Models.default_model() == "gpt-5"
        # Restart for other tests
        ensure_registry_started()
      else
        # No registry running — should still return gpt-5 safely
        assert Models.default_model() == "gpt-5"
      end
    end

    test "returns first model from ModelRegistry when available" do
      ensure_registry_started()

      model = Models.default_model()
      assert is_binary(model)
      assert model != ""

      names = CodePuppyControl.ModelRegistry.list_model_names()

      if names != [] do
        assert model == List.first(names)
      end
    end
  end

  describe "first_registry_model/0" do
    test "returns nil when ModelRegistry is not running" do
      original_pid = GenServer.whereis(CodePuppyControl.ModelRegistry)

      if original_pid do
        GenServer.stop(CodePuppyControl.ModelRegistry, :shutdown)
        assert Models.first_registry_model() == nil
        ensure_registry_started()
      else
        assert Models.first_registry_model() == nil
      end
    end

    test "returns first model name when registry is populated" do
      ensure_registry_started()

      names = CodePuppyControl.ModelRegistry.list_model_names()

      if names != [] do
        assert Models.first_registry_model() == List.first(names)
      else
        assert Models.first_registry_model() == nil
      end
    end
  end

  describe "set_global_model/1" do
    test "persists model to config" do
      ensure_writer_started()
      Models.set_global_model("claude-sonnet")

      Loader.load(@test_cfg)
      assert Models.global_model_name() == "claude-sonnet"
    end
  end

  describe "temperature/0" do
    test "returns nil when not set" do
      assert Models.temperature() == nil
    end

    test "parses float temperature" do
      File.write!(@test_cfg, "[puppy]\ntemperature = 0.7\n")
      Loader.load(@test_cfg)

      assert Models.temperature() == 0.7
    end

    test "clamps to 0-2 range" do
      File.write!(@test_cfg, "[puppy]\ntemperature = 5.0\n")
      Loader.load(@test_cfg)

      assert Models.temperature() == 2.0
    end
  end

  describe "set_temperature/1" do
    test "sets and clears temperature" do
      ensure_writer_started()

      Models.set_temperature(1.5)
      Loader.load(@test_cfg)
      assert Models.temperature() == 1.5

      Models.set_temperature(nil)
      Loader.load(@test_cfg)
      assert Models.temperature() == nil
    end
  end

  describe "agent_pinned_model/1" do
    test "returns nil for unpinned agent" do
      assert Models.agent_pinned_model("my-agent") == nil
    end

    test "returns pinned model" do
      File.write!(@test_cfg, "[puppy]\nagent_model_my-agent = gpt-5\n")
      Loader.load(@test_cfg)

      assert Models.agent_pinned_model("my-agent") == "gpt-5"
    end
  end

  describe "set_agent_pinned_model/2 and clear/1" do
    test "pins and clears agent model" do
      ensure_writer_started()

      Models.set_agent_pinned_model("agent1", "gpt-5")
      Loader.load(@test_cfg)
      assert Models.agent_pinned_model("agent1") == "gpt-5"

      Models.clear_agent_pinned_model("agent1")
      Loader.load(@test_cfg)
      assert Models.agent_pinned_model("agent1") == nil
    end
  end

  describe "all_agent_pinned_models/0" do
    test "returns map of all pinnings" do
      File.write!(@test_cfg, "[puppy]\nagent_model_a = m1\nagent_model_b = m2\nother = val\n")
      Loader.load(@test_cfg)

      result = Models.all_agent_pinned_models()
      assert result == %{"a" => "m1", "b" => "m2"}
    end
  end

  describe "openai_reasoning_effort/0" do
    test "defaults to medium" do
      assert Models.openai_reasoning_effort() == "medium"
    end

    test "returns configured value" do
      File.write!(@test_cfg, "[puppy]\nopenai_reasoning_effort = high\n")
      Loader.load(@test_cfg)

      assert Models.openai_reasoning_effort() == "high"
    end
  end

  describe "set_openai_reasoning_effort/1" do
    test "validates input" do
      ensure_writer_started()

      assert {:error, _} = Models.set_openai_reasoning_effort("invalid")
      assert :ok = Models.set_openai_reasoning_effort("low")
    end
  end

  describe "openai_verbosity/0" do
    test "defaults to medium" do
      assert Models.openai_verbosity() == "medium"
    end
  end

  describe "get_model_setting/2" do
    test "returns nil for unset setting" do
      assert Models.get_model_setting("gpt-5", "temperature") == nil
    end

    test "returns parsed value" do
      File.write!(@test_cfg, "[puppy]\nmodel_settings_gpt_5_temperature = 0.8\n")
      Loader.load(@test_cfg)

      assert Models.get_model_setting("gpt-5", "temperature") == 0.8
    end
  end

  describe "get_all_model_settings/1" do
    test "returns all settings for a model" do
      File.write!(@test_cfg, """
      [puppy]
      model_settings_gpt_5_temperature = 0.8
      model_settings_gpt_5_seed = 42
      other_key = not_this
      """)

      Loader.load(@test_cfg)

      result = Models.get_all_model_settings("gpt-5")
      assert result["temperature"] == 0.8
      assert result["seed"] == 42
      refute Map.has_key?(result, "other_key")
    end
  end

  defp ensure_writer_started do
    case Writer.start_link() do
      {:ok, _} -> :ok
      {:error, {:already_started, _}} -> :ok
    end
  end

  defp ensure_registry_started do
    case CodePuppyControl.ModelRegistry.start_link([]) do
      {:ok, _} -> :ok
      {:error, {:already_started, _}} -> :ok
    end
  end
end
