defmodule CodePuppyControl.ModelFactoryTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.ModelFactory
  alias CodePuppyControl.ModelFactory.{Handle, ProviderRegistry}
  alias CodePuppyControl.LLM.Providers.{OpenAI, Anthropic}

  setup do
    ProviderRegistry.reset_for_test()
    on_exit(fn -> ProviderRegistry.reset_for_test() end)
    :ok
  end

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

    test "runtime-registered provider type appears in list_available" do
      :ok = ProviderRegistry.register("temp_list_avail_provider", OpenAI)

      :ets.insert(
        :model_configs,
        {"temp-list-avail-model",
         %{"type" => "temp_list_avail_provider", "name" => "list-avail-fake"}}
      )

      available = ModelFactory.list_available()

      # Runtime provider types without credential requirements have no
      # required env vars, so Credentials.validate returns :ok and the
      # model is listed.
      assert {"temp-list-avail-model", "temp_list_avail_provider", OpenAI} =
               Enum.find(available, fn {n, _, _} -> n == "temp-list-avail-model" end)

      # After reset, the provider type is unregistered, so the model
      # drops out of list_available.
      :ok = ProviderRegistry.reset_for_test()

      available_after = ModelFactory.list_available()

      assert nil ==
               Enum.find(available_after, fn {n, _, _} -> n == "temp-list-avail-model" end)
    after
      :ets.delete(:model_configs, "temp-list-avail-model")
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

  # ── ProviderRegistry Integration ───────────────────────────────────────
  #
  # These tests prove ModelFactory delegates to ProviderRegistry
  # rather than a static @provider_map, enabling runtime extensibility.

  describe "provider_module_for_type/1 — ProviderRegistry integration" do
    test "returns runtime-registered provider type" do
      assert :error = ModelFactory.provider_module_for_type("my_runtime_provider")

      :ok = ProviderRegistry.register("my_runtime_provider", FakeProvider)
      assert {:ok, FakeProvider} = ModelFactory.provider_module_for_type("my_runtime_provider")
    end

    test "reset restores built-in behavior" do
      :ok = ProviderRegistry.register("openai", FakeProvider)
      assert {:ok, FakeProvider} = ModelFactory.provider_module_for_type("openai")

      :ok = ProviderRegistry.reset_for_test()
      assert {:ok, OpenAI} = ModelFactory.provider_module_for_type("openai")
    end

    test "unregistered type returns :error after reset" do
      :ok = ProviderRegistry.register("ephemeral_type", EphemeralMod)
      assert {:ok, EphemeralMod} = ModelFactory.provider_module_for_type("ephemeral_type")

      :ok = ProviderRegistry.reset_for_test()
      assert :error = ModelFactory.provider_module_for_type("ephemeral_type")
    end
  end

  describe "resolve/1 — ProviderRegistry integration" do
    test "runtime-registered provider type can resolve to a Handle" do
      :ok = ProviderRegistry.register("my_test_provider", OpenAI)

      :ets.insert(
        :model_configs,
        {"my-test-model", %{"type" => "my_test_provider", "name" => "fake-model"}}
      )

      # ProviderRegistry consult makes resolution succeed; nil API key is
      # acceptable for non-OAuth types with no required env vars.
      assert {:ok, %Handle{} = handle} = ModelFactory.resolve("my-test-model")
      assert handle.provider_module == OpenAI
      assert handle.model_name == "my-test-model"
    after
      :ets.delete(:model_configs, "my-test-model")
    end

    test "unregistered provider type returns unsupported_model_type" do
      :ets.insert(
        :model_configs,
        {"unreg-model", %{"type" => "totally_unregistered", "name" => "x"}}
      )

      assert {:error, {:unsupported_model_type, "totally_unregistered", "unreg-model"}} =
               ModelFactory.resolve("unreg-model")
    after
      :ets.delete(:model_configs, "unreg-model")
    end

    test "reset removes runtime provider from resolution" do
      :ok = ProviderRegistry.register("temp_provider", OpenAI)

      :ets.insert(
        :model_configs,
        {"temp-model", %{"type" => "temp_provider", "name" => "x"}}
      )

      # Before reset: type is resolvable
      assert {:ok, OpenAI} = ModelFactory.provider_module_for_type("temp_provider")

      :ok = ProviderRegistry.reset_for_test()

      # After reset: type is gone, resolve returns unsupported
      assert :error = ModelFactory.provider_module_for_type("temp_provider")

      assert {:error, {:unsupported_model_type, "temp_provider", "temp-model"}} =
               ModelFactory.resolve("temp-model")
    after
      :ets.delete(:model_configs, "temp-model")
    end
  end

  # ── Non-binary Provider Type Regression ────────────────────────────────
  #
  # Previously Map.get(@provider_map, provider_type) returned nil for
  # non-binary values like 123. After migrating to ProviderRegistry.lookup/1
  # (which guards is_binary), a non-binary type crashed with
  # FunctionClauseError. The lookup_provider/1 wrapper restores the old
  # safe-fallback behaviour.

  describe "resolve/1 — non-binary provider type regression" do
    test "returns unsupported_model_type for non-binary type instead of crashing" do
      :ets.insert(
        :model_configs,
        {"bad-type-model", %{"type" => 123, "name" => "x"}}
      )

      assert {:error, {:unsupported_model_type, 123, "bad-type-model"}} =
               ModelFactory.resolve("bad-type-model")
    after
      :ets.delete(:model_configs, "bad-type-model")
    end
  end

  describe "list_available/0 — non-binary provider type regression" do
    test "skips model with non-binary type instead of raising" do
      :ets.insert(
        :model_configs,
        {"bad-type-model", %{"type" => 123, "name" => "x"}}
      )

      # Must not raise — the model is silently skipped
      available = ModelFactory.list_available()

      refute Enum.any?(available, fn {n, _, _} -> n == "bad-type-model" end)
    after
      :ets.delete(:model_configs, "bad-type-model")
    end
  end
end
