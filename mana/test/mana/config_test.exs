defmodule Mana.ConfigTest do
  @moduledoc """
  Tests for Mana.Config module.
  """

  use ExUnit.Case, async: false

  alias Mana.Config
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

      # Cleanup environment variables set during tests
      System.delete_env("OPENAI_API_KEY")
      System.delete_env("ANTHROPIC_API_KEY")
      System.delete_env("GEMINI_API_KEY")
      System.delete_env("GROQ_API_KEY")
      System.delete_env("OLLAMA_API_KEY")
      System.delete_env("COHERE_API_KEY")
    end)

    :ok
  end

  describe "config_keys/0" do
    test "returns map of all configuration keys" do
      keys = Config.config_keys()

      assert is_map(keys)
      assert Map.has_key?(keys, :yolo_mode)
      assert Map.has_key?(keys, :streaming_enabled)
      assert Map.has_key?(keys, :global_model_name)
      assert Map.has_key?(keys, :temperature)
      assert Map.has_key?(keys, :max_tokens)
      assert Map.has_key?(keys, :log_level)
    end

    test "each key has default and type fields" do
      keys = Config.config_keys()

      Enum.each(keys, fn {_key, spec} ->
        assert Map.has_key?(spec, :default)
        assert Map.has_key?(spec, :type)
      end)
    end
  end

  describe "boolean accessor functions" do
    test "yolo_mode?/0 returns default false" do
      assert Config.yolo_mode?() == false
    end

    test "yolo_mode?/0 returns stored value" do
      Store.put(:yolo_mode, true)
      assert Config.yolo_mode?() == true
    end

    test "streaming_enabled?/0 returns default true" do
      assert Config.streaming_enabled?() == true
    end

    test "streaming_enabled?/0 returns stored value" do
      Store.put(:streaming_enabled, false)
      assert Config.streaming_enabled?() == false
    end
  end

  describe "value accessor functions" do
    test "global_model_name/0 returns default 'gpt-4'" do
      assert Config.global_model_name() == "gpt-4"
    end

    test "global_model_name/0 returns stored value" do
      Store.put(:global_model_name, "claude-3")
      assert Config.global_model_name() == "claude-3"
    end

    test "temperature/0 returns default 0.7" do
      assert Config.temperature() == 0.7
    end

    test "temperature/0 returns stored value" do
      Store.put(:temperature, 1.0)
      assert Config.temperature() == 1.0
    end

    test "max_tokens/0 returns default 4096" do
      assert Config.max_tokens() == 4096
    end

    test "max_tokens/0 returns stored value" do
      Store.put(:max_tokens, 8192)
      assert Config.max_tokens() == 8192
    end

    test "log_level/0 returns default 'info'" do
      assert Config.log_level() == "info"
    end

    test "log_level/0 returns stored value" do
      Store.put(:log_level, "debug")
      assert Config.log_level() == "debug"
    end
  end

  describe "get/2" do
    test "returns default for unset keys" do
      assert Config.get(:unknown_key, "default") == "default"
    end

    test "returns stored value" do
      Store.put(:custom_key, "custom_value")
      assert Config.get(:custom_key, "default") == "custom_value"
    end

    test "falls back to schema default for known keys" do
      # Temperature should have its default from config_keys
      assert Config.get(:temperature, nil) == 0.7
    end
  end

  describe "put/2" do
    test "stores value through Store" do
      assert Config.put(:put_test_key, "put_test_value") == :ok
      assert Store.get(:put_test_key, nil) == "put_test_value"
    end
  end

  describe "api_key/1" do
    test "returns nil for unknown provider" do
      assert Config.api_key("unknown_provider") == nil
    end

    test "returns nil when env var is not set" do
      System.delete_env("OPENAI_API_KEY")
      assert Config.api_key("openai") == nil
    end

    test "returns API key from environment variable" do
      System.put_env("OPENAI_API_KEY", "sk-test-openai-key")
      assert Config.api_key("openai") == "sk-test-openai-key"
    end

    test "is case insensitive for provider name" do
      System.put_env("ANTHROPIC_API_KEY", "sk-test-anthropic-key")
      assert Config.api_key("ANTHROPIC") == "sk-test-anthropic-key"
      assert Config.api_key("anthropic") == "sk-test-anthropic-key"
      assert Config.api_key("Anthropic") == "sk-test-anthropic-key"
    end

    test "supports all configured providers" do
      System.put_env("OPENAI_API_KEY", "openai-key")
      System.put_env("ANTHROPIC_API_KEY", "anthropic-key")
      System.put_env("GEMINI_API_KEY", "gemini-key")
      System.put_env("GROQ_API_KEY", "groq-key")
      System.put_env("OLLAMA_API_KEY", "ollama-key")
      System.put_env("COHERE_API_KEY", "cohere-key")

      assert Config.api_key("openai") == "openai-key"
      assert Config.api_key("anthropic") == "anthropic-key"
      assert Config.api_key("gemini") == "gemini-key"
      assert Config.api_key("groq") == "groq-key"
      assert Config.api_key("ollama") == "ollama-key"
      assert Config.api_key("cohere") == "cohere-key"
    end
  end

  describe "api_keys/0" do
    test "returns empty map when no API keys are set" do
      assert Config.api_keys() == %{}
    end

    test "returns map of all configured API keys" do
      System.put_env("OPENAI_API_KEY", "openai-key")
      System.put_env("ANTHROPIC_API_KEY", "anthropic-key")

      keys = Config.api_keys()

      assert keys["openai"] == "openai-key"
      assert keys["anthropic"] == "anthropic-key"
      refute Map.has_key?(keys, "gemini")
    end

    test "only includes keys that are set" do
      System.put_env("GROQ_API_KEY", "groq-key")

      keys = Config.api_keys()

      assert map_size(keys) == 1
      assert keys["groq"] == "groq-key"
    end
  end

  describe "Schema macro" do
    test "custom schema module can be created" do
      defmodule TestConfigSchema do
        use Config.Schema,
          keys: %{
            custom_setting: %{default: "default_value", type: :string},
            feature_enabled: %{default: false, type: :boolean},
            max_count: %{default: 100, type: :integer}
          }
      end

      assert TestConfigSchema.config_keys() == %{
               custom_setting: %{default: "default_value", type: :string},
               feature_enabled: %{default: false, type: :boolean},
               max_count: %{default: 100, type: :integer}
             }

      assert TestConfigSchema.custom_setting() == "default_value"
      assert TestConfigSchema.feature_enabled?() == false
      assert TestConfigSchema.max_count() == 100
    end
  end
end
