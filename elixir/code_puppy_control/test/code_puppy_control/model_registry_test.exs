defmodule CodePuppyControl.ModelRegistryTest do
  @moduledoc """
  Tests for the ModelRegistry GenServer.

  Covers:
  - GenServer startup and initialization
  - Config loading and retrieval
  - Reload functionality
  - Model type resolution
  - Type supported checks
  - Listing model names and types
  - Concurrent read access
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.ModelRegistry

  # ============================================================================
  # Setup
  # ============================================================================

  setup do
    # Ensure the registry is running
    start_supervised!(ModelRegistry)
    :ok
  end

  # ============================================================================
  # Startup Tests
  # ============================================================================

  describe "startup" do
    test "starts successfully and loads bundled models" do
      # The registry should have started in setup and loaded models
      configs = ModelRegistry.get_all_configs()
      assert is_map(configs)
      assert map_size(configs) >= 5
    end

    test "loaded models have expected keys" do
      config = ModelRegistry.get_config("zai-glm-5-turbo-coding")
      assert is_map(config)
      assert config["type"] == "zai_coding"
      assert config["provider"] == "zai"
      assert config["name"] == "glm-5-turbo"
      assert config["context_length"] == 200_000
    end
  end

  # ============================================================================
  # Config Retrieval Tests
  # ============================================================================

  describe "get_config/1" do
    test "returns config for known model" do
      config = ModelRegistry.get_config("firepass-kimi-k2p5-turbo")
      assert is_map(config)
      assert config["type"] == "custom_openai"
      assert config["provider"] == "firepass"
    end

    test "returns nil for unknown model" do
      assert ModelRegistry.get_config("totally-unknown-model-12345") == nil
    end

    test "handles multiple model lookups" do
      models = [
        "zai-glm-5-turbo-coding",
        "zai-glm-5-turbo-api",
        "zai-glm-5.1-coding",
        "zai-glm-5.1-api"
      ]

      for model <- models do
        config = ModelRegistry.get_config(model)
        assert is_map(config), "Expected config for #{model}"
        assert config["type"] in ["zai_coding", "zai_api"]
        assert config["provider"] == "zai"
      end
    end
  end

  describe "get_all_configs/0" do
    test "returns all configs as a map" do
      configs = ModelRegistry.get_all_configs()
      assert is_map(configs)

      # Should include all bundled models
      assert "zai-glm-5-turbo-coding" in Map.keys(configs)
      assert "firepass-kimi-k2p5-turbo" in Map.keys(configs)

      # Each config should be a map
      for {name, config} <- configs do
        assert is_binary(name)
        assert is_map(config)
        assert config["type"] != nil, "Model #{name} should have a type"
      end
    end
  end

  # ============================================================================
  # Reload Tests
  # ============================================================================

  describe "reload/0" do
    test "reloads configs successfully" do
      # Get initial count
      initial_count = ModelRegistry.get_all_configs() |> map_size()
      assert initial_count > 0

      # Reload
      assert :ok = ModelRegistry.reload()

      # Verify configs still loaded
      new_count = ModelRegistry.get_all_configs() |> map_size()
      assert new_count == initial_count
    end

    test "reload refreshes data (can pick up changes if files change)" do
      # This test verifies the reload mechanism works
      # In a real scenario, files could change between reloads

      # Verify initial state
      assert is_map(ModelRegistry.get_all_configs())

      # Reload should succeed
      assert :ok = ModelRegistry.reload()

      # Verify still works after reload
      assert is_map(ModelRegistry.get_all_configs())
      assert ModelRegistry.get_config("zai-glm-5-turbo-coding") != nil
    end
  end

  # ============================================================================
  # Model Type Tests
  # ============================================================================

  describe "get_model_type/1" do
    test "extracts type from config" do
      assert ModelRegistry.get_model_type(%{"type" => "openai"}) == "openai"
      assert ModelRegistry.get_model_type(%{"type" => "anthropic"}) == "anthropic"
      assert ModelRegistry.get_model_type(%{"type" => "zai_coding"}) == "zai_coding"
    end

    test "returns nil for config without type" do
      assert ModelRegistry.get_model_type(%{"name" => "test"}) == nil
      assert ModelRegistry.get_model_type(%{}) == nil
    end

    test "returns nil for invalid input" do
      assert ModelRegistry.get_model_type(nil) == nil
      assert ModelRegistry.get_model_type("string") == nil
      assert ModelRegistry.get_model_type(123) == nil
    end

    test "works with actual loaded configs" do
      config = ModelRegistry.get_config("zai-glm-5-turbo-coding")
      assert ModelRegistry.get_model_type(config) == "zai_coding"
    end
  end

  describe "is_type_supported/1" do
    test "returns true for known types" do
      known_types = [
        "openai",
        "anthropic",
        "custom_anthropic",
        "azure_openai",
        "custom_openai",
        "zai_coding",
        "zai_api",
        "cerebras",
        "openrouter",
        "round_robin",
        "gemini",
        "gemini_oauth",
        "custom_gemini"
      ]

      for type <- known_types do
        assert ModelRegistry.is_type_supported(type), "Type #{type} should be supported"
      end
    end

    test "returns false for unknown types" do
      refute ModelRegistry.is_type_supported("unknown_type")
      refute ModelRegistry.is_type_supported("random_type_123")
      refute ModelRegistry.is_type_supported("")
    end

    test "handles edge cases" do
      refute ModelRegistry.is_type_supported(nil)
      refute ModelRegistry.is_type_supported(123)
      refute ModelRegistry.is_type_supported(:atom)
    end
  end

  describe "known_model_types/0" do
    test "returns all known model types" do
      types = ModelRegistry.known_model_types()
      assert is_list(types)
      assert length(types) >= 10

      # Verify it includes all expected types
      assert "openai" in types
      assert "anthropic" in types
      assert "zai_coding" in types
      assert "round_robin" in types
    end
  end

  describe "list_model_types/0" do
    test "returns types from currently loaded configs" do
      types = ModelRegistry.list_model_types()
      assert is_list(types)

      # Based on bundled models.json, should have these types
      assert "zai_coding" in types
      assert "zai_api" in types
      assert "custom_openai" in types
    end

    test "returns only unique types" do
      types = ModelRegistry.list_model_types()
      unique_types = Enum.uniq(types)
      assert length(types) == length(unique_types)
    end
  end

  # ============================================================================
  # Listing Tests
  # ============================================================================

  describe "list_model_names/0" do
    test "returns all model names" do
      names = ModelRegistry.list_model_names()
      assert is_list(names)
      assert length(names) >= 5

      # Check for expected models from bundled models.json
      assert "zai-glm-5-turbo-coding" in names
      assert "firepass-kimi-k2p5-turbo" in names
      assert "zai-glm-5-turbo-api" in names
      assert "zai-glm-5.1-coding" in names
      assert "zai-glm-5.1-api" in names
    end

    test "returns sorted list" do
      names = ModelRegistry.list_model_names()
      assert names == Enum.sort(names)
    end

    test "returns consistent results after reload" do
      names_before = ModelRegistry.list_model_names()
      ModelRegistry.reload()
      names_after = ModelRegistry.list_model_names()

      assert names_before == names_after
    end
  end

  # ============================================================================
  # Concurrent Access Tests
  # ============================================================================

  describe "concurrent reads" do
    test "handles concurrent config lookups" do
      # Create 100 concurrent tasks that all read configs
      tasks =
        for _ <- 1..100 do
          Task.async(fn ->
            ModelRegistry.get_config("zai-glm-5-turbo-coding")
          end)
        end

      results = Task.await_many(tasks)

      # All should return the same config
      first_result = hd(results)
      assert is_map(first_result)
      assert first_result["type"] == "zai_coding"

      # Verify all results are identical
      assert Enum.all?(results, fn r -> r == first_result end)
    end

    test "handles concurrent list operations" do
      # Mix of get_all_configs and list_model_names concurrently
      tasks =
        for i <- 1..50 do
          Task.async(fn ->
            if rem(i, 2) == 0 do
              ModelRegistry.get_all_configs() |> map_size()
            else
              ModelRegistry.list_model_names() |> length()
            end
          end)
        end

      results = Task.await_many(tasks)

      # All should return positive counts
      assert Enum.all?(results, fn count -> count >= 5 end)
    end

    test "reads during reload are safe" do
      # Start a bunch of concurrent readers
      reader_tasks =
        for _ <- 1..50 do
          Task.async(fn ->
            for _ <- 1..10 do
              _ = ModelRegistry.get_config("zai-glm-5-turbo-coding")
              _ = ModelRegistry.list_model_names()
              :ok
            end
          end)
        end

      # Trigger a reload while reads are happening
      :ok = ModelRegistry.reload()

      # Wait for all readers to complete
      results = Task.await_many(reader_tasks)

      # Each task returns a list of :ok results (10 per task)
      assert Enum.all?(results, fn task_results ->
               is_list(task_results) and Enum.all?(task_results, &(&1 == :ok))
             end)

      # Verify data integrity after reload
      configs = ModelRegistry.get_all_configs()
      assert map_size(configs) >= 5
      assert ModelRegistry.get_config("zai-glm-5-turbo-coding") != nil
    end
  end

  # ============================================================================
  # Integration Tests
  # ============================================================================

  describe "integration with actual loaded data" do
    test "loaded zai models have correct structure" do
      zai_models = [
        "zai-glm-5-turbo-coding",
        "zai-glm-5-turbo-api",
        "zai-glm-5.1-coding",
        "zai-glm-5.1-api"
      ]

      for model_name <- zai_models do
        config = ModelRegistry.get_config(model_name)
        assert is_map(config), "Expected config for #{model_name}"

        # Verify required keys
        assert config["type"] != nil, "#{model_name} should have a type"
        assert config["provider"] == "zai", "#{model_name} should have provider 'zai'"
        assert is_integer(config["context_length"]), "#{model_name} should have context_length"

        assert config["context_length"] == 200_000,
               "#{model_name} should have context_length 200000"
      end
    end

    test "loaded firepass model has correct structure" do
      config = ModelRegistry.get_config("firepass-kimi-k2p5-turbo")
      assert config["type"] == "custom_openai"
      assert config["provider"] == "firepass"
      assert config["context_length"] == 262_144

      # Check custom_endpoint structure
      assert is_map(config["custom_endpoint"])
      assert config["custom_endpoint"]["url"] == "https://api.fireworks.ai/inference/v1"
      assert config["custom_endpoint"]["api_key"] == "$FIREWORKS_API_KEY"
    end

    test "list_model_types matches actual loaded configs" do
      # Get all types from loaded configs
      loaded_types = ModelRegistry.list_model_types()

      # Get all configs and extract types manually
      configs = ModelRegistry.get_all_configs()

      extracted_types =
        configs
        |> Map.values()
        |> Enum.map(&Map.get(&1, "type"))
        |> Enum.reject(&is_nil/1)
        |> Enum.uniq()
        |> Enum.sort()

      assert loaded_types == extracted_types
    end
  end

  # ============================================================================
  # Edge Cases
  # ============================================================================

  describe "edge cases" do
    test "handles model names with special characters" do
      # Verify that existing models with dashes and dots work
      assert ModelRegistry.get_config("zai-glm-5.1-coding") != nil
      assert ModelRegistry.get_config("firepass-kimi-k2p5-turbo") != nil
    end

    test "empty string model name returns nil" do
      assert ModelRegistry.get_config("") == nil
    end

    test "very long model name returns nil" do
      long_name = String.duplicate("a", 1000)
      assert ModelRegistry.get_config(long_name) == nil
    end
  end
end
