defmodule CodePuppyControl.CLI.SlashCommands.Commands.AddModelTest do
  @moduledoc """
  Tests for AddModel: registration, dispatch, build_model_config,
  derive_provider_identity, unsupported_provider, and filter helpers.

  Persistence tests → add_model_persistence_test.exs
  Interactive path tests → add_model_interactive_test.exs

  Split to keep under the 600-line cap.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Dispatcher, Registry}
  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModel
  alias CodePuppyControl.ModelsDevParser.{ModelInfo, ProviderInfo}

  setup do
    # Start the SlashCommands Registry GenServer if not already running
    case Process.whereis(Registry) do
      nil -> start_supervised!({Registry, []})
      _pid -> :ok
    end

    Registry.clear()

    # Register /add_model command
    :ok =
      Registry.register(
        CommandInfo.new(
          name: "add_model",
          description: "Browse and add models from models.dev catalog",
          handler: &AddModel.handle_add_model/2,
          usage: "/add_model",
          category: "context"
        )
      )

    # Start the LockKeeper for concurrency-safe persistence
    case Process.whereis(CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistence.LockKeeper) do
      nil -> start_supervised!({CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistence.LockKeeper, []})
      _pid -> :ok
    end

    # Use a temp directory for extra_models.json
    tmp_dir = Path.join(System.tmp_dir!(), "cp_add_model_test_#{:erlang.unique_integer([:positive])}")
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

  # ── Registration & dispatch ──────────────────────────────────────────────

  describe "registration and dispatch" do
    test "/add_model is registered and dispatchable" do
      assert {:ok, _} = Registry.get("add_model")
    end

    test "/add_model appears in all_names for tab completion" do
      names = Registry.all_names()
      assert "add_model" in names
    end

    test "/add_model appears in list_all" do
      commands = Registry.list_all()
      assert Enum.any?(commands, &(&1.name == "add_model"))
    end

    test "/add_model is in context category" do
      commands = Registry.list_by_category("context")
      add_model_cmd = Enum.find(commands, &(&1.name == "add_model"))
      assert add_model_cmd != nil
      assert add_model_cmd.category == "context"
    end

    test "/add_model usage is correct" do
      {:ok, cmd} = Registry.get("add_model")
      assert cmd.usage == "/add_model"
    end

    test "/add_model dispatches via Dispatcher" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:ok, {:continue, _}} = Dispatcher.dispatch("/add_model", %{})
        end)

      assert is_binary(output)
    end
  end

  # ── build_model_config ───────────────────────────────────────────────────

  describe "build_model_config/2" do
    test "builds anthropic config correctly" do
      provider = %ProviderInfo{id: "anthropic", name: "Anthropic", env: ["ANTHROPIC_API_KEY"]}
      model = %ModelInfo{provider_id: "anthropic", model_id: "claude-3-opus", name: "Claude 3 Opus", context_length: 200_000, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["type"] == "anthropic"
      assert config["provider"] == "anthropic"
      assert config["name"] == "claude-3-opus"
      assert config["context_length"] == 200_000
      assert "extended_thinking" in config["supported_settings"]
    end

    test "builds openai config with gpt-5 reasoning effort" do
      provider = %ProviderInfo{id: "openai", name: "OpenAI", env: ["OPENAI_API_KEY"]}
      model = %ModelInfo{provider_id: "openai", model_id: "gpt-5-turbo", name: "GPT-5 Turbo", context_length: 128_000, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["type"] == "openai"
      assert config["name"] == "gpt-5-turbo"
      assert "reasoning_effort" in config["supported_settings"]
      assert "verbosity" in config["supported_settings"]
    end

    test "builds custom_openai config with endpoint" do
      provider = %ProviderInfo{id: "groq", name: "Groq", env: ["GROQ_API_KEY"], api: "https://api.groq.com/openai/v1"}
      model = %ModelInfo{provider_id: "groq", model_id: "llama-3", name: "Llama 3", context_length: 8192, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["type"] == "custom_openai"
      assert config["custom_endpoint"]["url"] == "https://api.groq.com/openai/v1"
      assert config["custom_endpoint"]["api_key"] == "$GROQ_API_KEY"
    end

    test "builds custom_openai config with hardcoded fallback endpoint" do
      provider = %ProviderInfo{id: "groq", name: "Groq", env: ["GROQ_API_KEY"], api: ""}
      model = %ModelInfo{provider_id: "groq", model_id: "llama-3", name: "Llama 3", context_length: 8192, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["type"] == "custom_openai"
      assert config["custom_endpoint"]["url"] == "https://api.groq.com/openai/v1"
    end

    test "builds minimax config with custom_anthropic and stripped /v1" do
      provider = %ProviderInfo{id: "minimax", name: "MiniMax", env: ["MINIMAX_API_KEY"], api: "https://api.minimax.io/anthropic/v1"}
      model = %ModelInfo{provider_id: "minimax", model_id: "minimax-01", name: "MiniMax 01", context_length: 100_000, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["type"] == "custom_anthropic"
      assert config["custom_endpoint"]["url"] == "https://api.minimax.io/anthropic"
      assert config["custom_endpoint"]["api_key"] == "$MINIMAX_API_KEY"
    end

    test "builds gemini config" do
      provider = %ProviderInfo{id: "google", name: "Google", env: ["GOOGLE_API_KEY"]}
      model = %ModelInfo{provider_id: "google", model_id: "gemini-2.5-pro", name: "Gemini 2.5 Pro", context_length: 1_000_000, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["type"] == "gemini"
      assert config["name"] == "gemini-2.5-pro"
      assert config["context_length"] == 1_000_000
    end

    test "kimi-for-coding provider uses kimi-for-coding as name" do
      provider = %ProviderInfo{id: "kimi-for-coding", name: "Kimi", env: ["KIMI_API_KEY"]}
      model = %ModelInfo{provider_id: "kimi-for-coding", model_id: "kimi-k2-thinking", name: "Kimi K2", context_length: 128_000, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["name"] == "kimi-for-coding"
    end

    test "unknown provider falls back to custom_openai" do
      provider = %ProviderInfo{id: "some-new-provider", name: "New Provider", env: ["NEW_API_KEY"], api: "https://api.newprovider.com/v1"}
      model = %ModelInfo{provider_id: "some-new-provider", model_id: "cool-model", name: "Cool Model", context_length: 64_000, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      assert config["type"] == "custom_openai"
    end

    test "omits context_length when zero" do
      provider = %ProviderInfo{id: "openai", name: "OpenAI", env: ["OPENAI_API_KEY"]}
      model = %ModelInfo{provider_id: "openai", model_id: "test-model", name: "Test", context_length: 0, tool_call: true}

      config = AddModel.build_model_config(model, provider)

      refute Map.has_key?(config, "context_length")
    end
  end

  # ── derive_provider_identity ─────────────────────────────────────────────

  describe "derive_provider_identity/1" do
    test "maps known providers to identity strings" do
      assert AddModel.derive_provider_identity(%ProviderInfo{id: "openai", name: "OpenAI", env: []}) == "openai"
      assert AddModel.derive_provider_identity(%ProviderInfo{id: "together-ai", name: "Together", env: []}) == "together_ai"
      assert AddModel.derive_provider_identity(%ProviderInfo{id: "anthropic", name: "Anthropic", env: []}) == "anthropic"
    end

    test "falls back to hyphen-to-underscore conversion" do
      assert AddModel.derive_provider_identity(%ProviderInfo{id: "my-cool-provider", name: "Cool", env: []}) == "my_cool_provider"
    end
  end

  # ── unsupported_provider? ────────────────────────────────────────────────

  describe "unsupported_provider?/1" do
    test "amazon-bedrock is unsupported" do
      assert AddModel.unsupported_provider?("amazon-bedrock")
    end

    test "google-vertex is unsupported" do
      assert AddModel.unsupported_provider?("google-vertex")
    end

    test "openai is supported" do
      refute AddModel.unsupported_provider?("openai")
    end

    test "anthropic is supported" do
      refute AddModel.unsupported_provider?("anthropic")
    end
  end

  describe "unsupported_reason/1" do
    test "returns reason for unsupported provider" do
      assert AddModel.unsupported_reason("amazon-bedrock") =~ "AWS SigV4"
    end

    test "returns nil for supported provider" do
      assert AddModel.unsupported_reason("openai") == nil
    end
  end

  # ── Pagination helpers ──────────────────────────────────────────────────

  describe "filter_providers/2" do
    test "filters providers by name substring" do
      providers = [
        %ProviderInfo{id: "openai", name: "OpenAI", env: []},
        %ProviderInfo{id: "anthropic", name: "Anthropic", env: []},
        %ProviderInfo{id: "google", name: "Google", env: []}
      ]

      result = AddModel.filter_providers(providers, "open")
      assert length(result) == 1
      assert hd(result).id == "openai"
    end

    test "filters providers by id substring" do
      providers = [
        %ProviderInfo{id: "openai", name: "OpenAI", env: []},
        %ProviderInfo{id: "anthropic", name: "Anthropic", env: []}
      ]

      result = AddModel.filter_providers(providers, "anth")
      assert length(result) == 1
      assert hd(result).id == "anthropic"
    end

    test "returns empty list for no match" do
      providers = [%ProviderInfo{id: "openai", name: "OpenAI", env: []}]
      result = AddModel.filter_providers(providers, "zzz")
      assert result == []
    end
  end

  describe "filter_models/2" do
    test "filters models by name substring" do
      models = [
        %ModelInfo{provider_id: "openai", model_id: "gpt-5", name: "GPT-5 Turbo"},
        %ModelInfo{provider_id: "openai", model_id: "o3", name: "o3"},
        %ModelInfo{provider_id: "anthropic", model_id: "claude-3", name: "Claude 3 Opus"}
      ]

      result = AddModel.filter_models(models, "claude")
      assert length(result) == 1
      assert hd(result).model_id == "claude-3"
    end

    test "filters models by model_id substring" do
      models = [
        %ModelInfo{provider_id: "openai", model_id: "gpt-5-turbo", name: "GPT-5 Turbo"},
        %ModelInfo{provider_id: "openai", model_id: "o3-mini", name: "o3 Mini"}
      ]

      result = AddModel.filter_models(models, "gpt")
      assert length(result) == 1
      assert hd(result).model_id == "gpt-5-turbo"
    end
  end
end
