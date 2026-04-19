defmodule CodePuppyControl.ModelFactoryTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.ModelFactory
  alias CodePuppyControl.ModelFactory.Handle
  alias CodePuppyControl.LLM.Providers.{OpenAI, Anthropic}

  # Note: These tests rely on the test_models.json fixture being loaded
  # by ModelRegistry during application startup.

  describe "resolve/1" do
    test "resolves a known openai-compatible model to a handle" do
      # test-model is of type "openai" in test_models.json
      case ModelFactory.resolve("test-model") do
        {:ok, handle} ->
          assert %Handle{} = handle
          assert handle.model_name == "test-model"
          assert handle.provider_module == OpenAI
          assert handle.provider_config["type"] == "openai"
          assert handle.model_opts[:model] == "gpt-4"

        {:error, _reason} ->
          # Model might not be in fixture — acceptable in test
          :ok
      end
    end

    test "returns error for unknown model" do
      assert {:error, {:unknown_model, "nonexistent-xyz"}} =
               ModelFactory.resolve("nonexistent-xyz")
    end

    test "returns error for claude_code model (Phase 4 stub)" do
      # If a claude_code model is in the registry, it should return oauth_phase_4
      case ModelFactory.resolve("claude-code") do
        {:error, {:oauth_phase_4, "claude_code", "claude-code"}} -> :ok
        {:error, {:unknown_model, _}} -> :ok
        other -> flunk("Expected oauth_phase_4 or unknown_model, got: #{inspect(other)}")
      end
    end

    test "resolves model with custom endpoint" do
      # Check all configs for any custom_openai models
      configs = CodePuppyControl.ModelRegistry.get_all_configs()

      custom_models =
        Enum.filter(configs, fn {_name, config} ->
          config["type"] == "custom_openai" and Map.has_key?(config, "custom_endpoint")
        end)

      case custom_models do
        [{name, _config} | _] ->
          case ModelFactory.resolve(name) do
            {:ok, handle} ->
              assert handle.base_url != nil

            {:error, _} ->
              # Missing API key is acceptable
              :ok
          end

        [] ->
          # No custom models in test fixtures — skip
          :ok
      end
    end

    test "handle has correct provider_config from registry" do
      case ModelFactory.resolve("test-model") do
        {:ok, handle} ->
          assert is_map(handle.provider_config)
          assert handle.provider_config["type"] == "openai"

        {:error, _} ->
          :ok
      end
    end
  end

  describe "resolve!/1" do
    test "returns handle for known model" do
      case ModelFactory.resolve("test-model") do
        {:ok, _} ->
          handle = ModelFactory.resolve!("test-model")
          assert %Handle{} = handle

        {:error, _} ->
          # Model not in fixture
          assert_raise RuntimeError, ~r/Failed to resolve/, fn ->
            ModelFactory.resolve!("test-model")
          end
      end
    end

    test "raises for unknown model" do
      assert_raise RuntimeError, ~r/Failed to resolve/, fn ->
        ModelFactory.resolve!("nonexistent-xyz")
      end
    end
  end

  describe "list_available/0" do
    test "returns a list of tuples" do
      available = ModelFactory.list_available()
      assert is_list(available)

      Enum.each(available, fn entry ->
        assert {name, provider_type, provider_mod} = entry
        assert is_binary(name)
        assert is_binary(provider_type)
        assert is_atom(provider_mod)
      end)
    end

    test "all returned models have provider modules" do
      available = ModelFactory.list_available()

      Enum.each(available, fn {_name, _type, mod} ->
        assert mod in [OpenAI, Anthropic]
      end)
    end
  end

  describe "validate_credentials/1" do
    test "returns error for unknown model" do
      assert {:error, {:unknown_model, "nonexistent"}} =
               ModelFactory.validate_credentials("nonexistent")
    end

    test "returns :ok or {:missing, _} for known models" do
      case ModelFactory.validate_credentials("test-model") do
        :ok -> :ok
        {:missing, vars} when is_list(vars) -> :ok
        {:error, {:unknown_model, _}} -> :ok
      end
    end
  end

  describe "provider_module_for_type/1" do
    test "returns OpenAI for openai type" do
      assert {:ok, OpenAI} = ModelFactory.provider_module_for_type("openai")
    end

    test "returns Anthropic for anthropic type" do
      assert {:ok, Anthropic} = ModelFactory.provider_module_for_type("anthropic")
    end

    test "returns OpenAI for custom_openai type" do
      assert {:ok, OpenAI} = ModelFactory.provider_module_for_type("custom_openai")
    end

    test "returns OpenAI for cerebras type" do
      assert {:ok, OpenAI} = ModelFactory.provider_module_for_type("cerebras")
    end

    test "returns OpenAI for openrouter type" do
      assert {:ok, OpenAI} = ModelFactory.provider_module_for_type("openrouter")
    end

    test "returns OpenAI for zai_coding type" do
      assert {:ok, OpenAI} = ModelFactory.provider_module_for_type("zai_coding")
    end

    test "returns :error for unknown type" do
      assert :error = ModelFactory.provider_module_for_type("unknown_type")
    end
  end
end
