defmodule Mana.Models.SettingsTest do
  @moduledoc """
  Tests for Mana.Models.Settings module.
  """

  use ExUnit.Case, async: true

  alias Mana.Models.Settings

  describe "make/1" do
    test "returns settings for Claude models" do
      settings = Settings.make("claude-3-sonnet-20240229")

      assert settings.provider == :anthropic
      assert settings.model_name == "claude-3-sonnet-20240229"
      assert settings.supports_tools == true
      assert settings.supports_vision == true
      assert settings.temperature == 0.7
    end

    test "returns settings for GPT models" do
      settings = Settings.make("gpt-4")

      assert settings.provider == :openai
      assert settings.model_name == "gpt-4"
      assert settings.supports_tools == true
      assert settings.supports_vision == false
    end

    test "returns settings for GPT-4 Vision models" do
      settings = Settings.make("gpt-4-vision-preview")

      assert settings.provider == :openai
      assert settings.model_name == "gpt-4-vision-preview"
      assert settings.supports_vision == true
    end

    test "returns settings for Ollama models" do
      settings = Settings.make("ollama/llama3.2")

      assert settings.provider == :ollama
      assert settings.model_name == "ollama/llama3.2"
      assert settings.supports_tools == true
      assert settings.supports_vision == false
    end

    test "returns default settings for unknown models" do
      settings = Settings.make("custom-model")

      assert settings.provider == :openai_compatible
      assert settings.model_name == "custom-model"
      assert settings.supports_tools == false
      assert settings.supports_vision == false
    end
  end

  describe "provider_module/1" do
    test "returns Anthropic module for anthropic provider" do
      settings = Settings.make("claude-3-sonnet-20240229")
      assert Settings.provider_module(settings) == Mana.Models.Providers.Anthropic
    end

    test "returns OpenAI module for openai provider" do
      settings = Settings.make("gpt-4")
      assert Settings.provider_module(settings) == Mana.Models.Providers.OpenAI
    end

    test "returns Ollama module for ollama provider" do
      settings = Settings.make("ollama/llama3.2")
      assert Settings.provider_module(settings) == Mana.Models.Providers.Ollama
    end

    test "returns OpenAICompatible module for default provider" do
      settings = Settings.make("custom-model")
      assert Settings.provider_module(settings) == Mana.Models.Providers.OpenAICompatible
    end
  end

  describe "max_tokens calculation" do
    test "returns appropriate max_tokens for Claude Opus" do
      settings = Settings.make("claude-3-opus-20240229")
      assert settings.max_tokens == 128_000
    end

    test "returns appropriate max_tokens for GPT-4o" do
      settings = Settings.make("gpt-4o")
      assert settings.max_tokens == 128_000
    end

    test "returns appropriate max_tokens for GPT-4" do
      settings = Settings.make("gpt-4")
      assert settings.max_tokens == 8192
    end

    test "returns appropriate max_tokens for GPT-3.5-turbo-16k" do
      settings = Settings.make("gpt-3.5-turbo-16k")
      assert settings.max_tokens == 16_384
    end

    test "returns default max_tokens for unknown models" do
      settings = Settings.make("unknown-model")
      assert settings.max_tokens == 4096
    end
  end
end
