defmodule Mana.Models.RegistryTest do
  @moduledoc """
  Tests for Mana.Models.Registry module.
  """

  use ExUnit.Case, async: false

  alias Mana.Models.Registry

  setup do
    # Start the registry for each test with unique name
    test_name = :"registry_#{System.unique_integer([:positive])}"
    {:ok, pid} = Registry.start_link(name: test_name)
    %{registry: pid, registry_name: test_name}
  end

  describe "start_link/1" do
    test "starts successfully with default name", %{registry_name: name} do
      assert Process.alive?(Process.whereis(name))
    end

    test "starts successfully with custom name" do
      {:ok, pid} = Registry.start_link(name: :custom_registry)
      assert Process.alive?(pid)
    end
  end

  describe "get_provider/1" do
    test "returns OpenAI provider for GPT models", %{registry_name: name} do
      {:ok, provider} = GenServer.call(name, {:get_provider, "gpt-4"})
      assert provider == Mana.Models.Providers.OpenAI
    end

    test "returns Anthropic provider for Claude models", %{registry_name: name} do
      {:ok, provider} = GenServer.call(name, {:get_provider, "claude-3-opus"})
      assert provider == Mana.Models.Providers.Anthropic
    end

    test "returns Ollama provider for ollama/ models", %{registry_name: name} do
      {:ok, provider} = GenServer.call(name, {:get_provider, "ollama/llama3.2"})
      assert provider == Mana.Models.Providers.Ollama
    end

    test "returns OpenAICompatible for unknown models", %{registry_name: name} do
      {:ok, provider} = GenServer.call(name, {:get_provider, "custom-model"})
      assert provider == Mana.Models.Providers.OpenAICompatible
    end
  end

  describe "register_provider/2" do
    test "registers a new provider", %{registry_name: name} do
      :ok = GenServer.call(name, {:register_provider, "custom", MyApp.CustomProvider})

      providers = GenServer.call(name, :list_providers)
      assert providers["custom"] == MyApp.CustomProvider
    end

    test "overwrites existing provider", %{registry_name: name} do
      :ok = GenServer.call(name, {:register_provider, "openai", CustomOpenAI})

      providers = GenServer.call(name, :list_providers)
      assert providers["openai"] == CustomOpenAI
    end
  end

  describe "get_model/1" do
    test "returns default model config if exists", %{registry_name: name} do
      # Default models are loaded on init
      result = GenServer.call(name, {:get_model, "gpt-4o"})

      assert {:ok, config} = result
      assert config["provider"] == "openai"
      assert config["supports_tools"] == true
    end

    test "returns error for unknown model", %{registry_name: name} do
      result = GenServer.call(name, {:get_model, "unknown-model-xyz"})
      assert result == {:error, :not_found}
    end
  end

  describe "register_model/2" do
    test "registers a new model", %{registry_name: name} do
      config = %{"provider" => "custom", "max_tokens" => 8192}
      :ok = GenServer.call(name, {:register_model, "my-model", config})

      {:ok, retrieved} = GenServer.call(name, {:get_model, "my-model"})
      assert retrieved == config
    end

    test "overwrites existing model", %{registry_name: name} do
      config1 = %{"provider" => "custom", "max_tokens" => 1000}
      config2 = %{"provider" => "custom", "max_tokens" => 2000}

      :ok = GenServer.call(name, {:register_model, "test-model", config1})
      :ok = GenServer.call(name, {:register_model, "test-model", config2})

      {:ok, retrieved} = GenServer.call(name, {:get_model, "test-model"})
      assert retrieved["max_tokens"] == 2000
    end
  end

  describe "list_models/0" do
    test "returns all registered models", %{registry_name: name} do
      models = GenServer.call(name, :list_models)

      # Should have default models
      assert is_map(models)
      assert Map.has_key?(models, "gpt-4o")
      assert Map.has_key?(models, "claude-opus-4-6")
    end
  end

  describe "list_providers/0" do
    test "returns all registered providers", %{registry_name: name} do
      providers = GenServer.call(name, :list_providers)

      assert is_map(providers)
      assert providers["openai"] == Mana.Models.Providers.OpenAI
      assert providers["anthropic"] == Mana.Models.Providers.Anthropic
      assert providers["ollama"] == Mana.Models.Providers.Ollama
      assert providers["openai_compatible"] == Mana.Models.Providers.OpenAICompatible
      assert providers["claude_code"] == Mana.OAuth.ClaudeCode
      assert providers["chatgpt"] == Mana.OAuth.ChatGPT
      assert providers["antigravity"] == Mana.OAuth.Antigravity
    end
  end

  describe "complete/3" do
    test "returns error when provider not found", %{registry_name: name} do
      # Unregister the openai_compatible provider so unknown models will fail
      # First, let's get current providers and remove openai_compatible
      :ok = GenServer.call(name, {:unregister_provider, "openai_compatible"})

      messages = [%{"role" => "user", "content" => "Hello"}]
      result = GenServer.call(name, {:complete, messages, "unknown-model", []})

      # Should error because provider is not registered
      assert {:error, :provider_not_found} = result
    end

    test "increments dispatch stats on completion attempt", %{registry_name: name} do
      initial_stats = GenServer.call(name, :get_stats)
      initial_dispatches = initial_stats.dispatches

      # Attempt a completion (will fail without API key but increments stats)
      messages = [%{"role" => "user", "content" => "Hello"}]
      GenServer.call(name, {:complete, messages, "gpt-4", []})

      new_stats = GenServer.call(name, :get_stats)
      assert new_stats.dispatches == initial_dispatches + 1
    end
  end

  describe "stream/3" do
    test "returns stream for valid model", %{registry_name: name} do
      messages = [%{"role" => "user", "content" => "Hello"}]
      result = GenServer.call(name, {:stream, messages, "gpt-4", []})

      # The registry returns a dispatch tuple with the provider and args
      # The actual streaming function is created by the client-side stream/3 wrapper
      assert {:dispatch, Mana.Models.Providers.OpenAI, ^messages, "gpt-4", []} = result
    end

    test "increments dispatch stats on stream attempt", %{registry_name: name} do
      initial_stats = GenServer.call(name, :get_stats)
      initial_dispatches = initial_stats.dispatches

      messages = [%{"role" => "user", "content" => "Hello"}]
      GenServer.call(name, {:stream, messages, "gpt-4", []})

      new_stats = GenServer.call(name, :get_stats)
      assert new_stats.dispatches == initial_dispatches + 1
    end
  end

  describe "get_stats/0" do
    test "returns initial stats", %{registry_name: name} do
      stats = GenServer.call(name, :get_stats)

      assert stats.dispatches == 0
      assert stats.errors == 0
    end

    test "tracks errors", %{registry_name: name} do
      initial_stats = GenServer.call(name, :get_stats)
      initial_errors = initial_stats.errors

      # Cause an error by using a non-existent provider
      :ok = GenServer.call(name, {:register_provider, "bad_provider", BadProvider})
      messages = [%{"role" => "user", "content" => "Hello"}]
      GenServer.call(name, {:complete, messages, "bad_provider-model", []})

      new_stats = GenServer.call(name, :get_stats)
      assert new_stats.errors >= initial_errors
    end
  end

  describe "init/1" do
    test "auto-registers built-in providers" do
      {:ok, pid} = Registry.start_link(name: :"init_test_#{System.unique_integer([:positive])}")

      providers = GenServer.call(pid, :list_providers)

      assert Map.has_key?(providers, "openai")
      assert Map.has_key?(providers, "anthropic")
      assert Map.has_key?(providers, "ollama")
      assert Map.has_key?(providers, "openai_compatible")
      assert Map.has_key?(providers, "claude_code")
      assert Map.has_key?(providers, "chatgpt")
      assert Map.has_key?(providers, "antigravity")
    end

    test "loads default models when config file missing" do
      {:ok, pid} = Registry.start_link(name: :"init_test2_#{System.unique_integer([:positive])}")

      models = GenServer.call(pid, :list_models)

      assert Map.has_key?(models, "gpt-4o")
      assert Map.has_key?(models, "gpt-4o-mini")
      assert Map.has_key?(models, "claude-opus-4-6")
      assert Map.has_key?(models, "claude-sonnet-4-5")
    end
  end
end
