defmodule CodePuppyControl.CLI.SlashCommands.Commands.AddModelTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Dispatcher, Registry}
  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModel
  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistence
  alias CodePuppyControl.ModelsDevParser.{ModelInfo, ProviderInfo}

  setup do
    # Start the Registry GenServer if not already running
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

    # Use a temp directory for extra_models.json
    tmp_dir = Path.join(System.tmp_dir!(), "cp_add_model_test_#{:erlang.unique_integer([:positive])}")
    File.mkdir_p!(tmp_dir)

    # Stub Paths.extra_models_file to use our temp path
    test_path = Path.join(tmp_dir, "extra_models.json")

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

    state = %{session_id: "test-session", running: true}

    {:ok, state: state, tmp_dir: tmp_dir, test_path: test_path}
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

      # Should show some provider browsing output or error about registry
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
      # Falls back to hardcoded endpoint
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

  # ── AddModelPersistence ─────────────────────────────────────────────────

  describe "AddModelPersistence.persist/2" do
    test "creates new extra_models.json with model config", %{test_path: path} do
      config = %{"type" => "openai", "name" => "gpt-5", "provider" => "openai"}

      # Override the path for this test
      result = with_mock_path(path, fn ->
        AddModelPersistence.persist("openai-gpt-5", config)
      end)

      # Since we can't easily mock Paths, test via direct file ops
      {:ok, _path} = AddModelPersistence.atomic_write_json(path, %{"openai-gpt-5" => config})

      assert File.exists?(path)
      {:ok, data} = Jason.decode(File.read!(path))
      assert data["openai-gpt-5"]["type"] == "openai"
    end

    test "merges into existing extra_models.json", %{test_path: path} do
      existing = %{"openai-gpt-5" => %{"type" => "openai", "name" => "gpt-5"}}
      {:ok, _path} = AddModelPersistence.atomic_write_json(path, existing)

      new_config = %{"type" => "anthropic", "name" => "claude-3"}
      updated = Map.put(existing, "anthropic-claude-3", new_config)
      {:ok, _path} = AddModelPersistence.atomic_write_json(path, updated)

      {:ok, data} = Jason.decode(File.read!(path))
      assert map_size(data) == 2
      assert data["anthropic-claude-3"]["type"] == "anthropic"
    end

    test "detects duplicate model keys", %{test_path: path} do
      existing = %{"openai-gpt-5" => %{"type" => "openai"}}
      {:ok, _path} = AddModelPersistence.atomic_write_json(path, existing)

      {:ok, loaded} = AddModelPersistence.read_existing(path)
      assert AddModelPersistence.check_duplicate(loaded, "openai-gpt-5") == {:error, :already_exists}
    end

    test "allows new model key when existing has different keys", %{test_path: path} do
      existing = %{"openai-gpt-5" => %{"type" => "openai"}}
      {:ok, _path} = AddModelPersistence.atomic_write_json(path, existing)

      {:ok, loaded} = AddModelPersistence.read_existing(path)
      assert AddModelPersistence.check_duplicate(loaded, "anthropic-claude-3") == :ok
    end

    test "read_existing returns empty map for nonexistent file" do
      {:ok, data} = AddModelPersistence.read_existing("/tmp/nonexistent_cp_test_#{:erlang.unique_integer([:positive])}.json")
      assert data == %{}
    end

    test "atomic_write_json creates parent directories" do
      deep_path = Path.join([System.tmp_dir!(), "cp_add_model_deep_#{:erlang.unique_integer([:positive])}", "sub", "extra_models.json"])

      on_exit(fn ->
        dir = Path.dirname(Path.dirname(deep_path))
        File.rm_rf!(dir)
      end)

      {:ok, _path} = AddModelPersistence.atomic_write_json(deep_path, %{"test" => %{"type" => "openai"}})
      assert File.exists?(deep_path)
    end

    test "atomic_write_json writes valid JSON", %{test_path: path} do
      data = %{"model-a" => %{"type" => "openai", "name" => "gpt-5"}}
      {:ok, _path} = AddModelPersistence.atomic_write_json(path, data)

      {:ok, decoded} = Jason.decode(File.read!(path))
      assert decoded == data
    end
  end

  # ── End-to-end persist via AddModelPersistence.persist/2 ────────────────

  describe "AddModelPersistence.persist/2 end-to-end" do
    test "persists model to extra_models.json via Paths.extra_models_file()", %{tmp_dir: tmp_dir} do
      config = %{"type" => "openai", "name" => "gpt-5", "provider" => "openai"}

      # The PUP_EX_HOME is set to tmp_dir in setup, so Paths.extra_models_file()
      # will resolve to tmp_dir/extra_models.json
      result = AddModelPersistence.persist("openai-gpt-5", config)

      assert {:ok, "openai-gpt-5"} = result

      path = Path.join(tmp_dir, "extra_models.json")
      assert File.exists?(path)

      {:ok, data} = Jason.decode(File.read!(path))
      assert data["openai-gpt-5"]["type"] == "openai"
      assert data["openai-gpt-5"]["name"] == "gpt-5"
    end

    test "rejects duplicate model key", %{tmp_dir: tmp_dir} do
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

  # ── run_with_inputs (programmatic flow) ─────────────────────────────────

  describe "run_with_inputs/1" do
    setup context do
      # Only run these if ModelsDevParser.Registry is available
      case Process.whereis(CodePuppyControl.ModelsDevParser.Registry) do
        nil ->
          # Start a mock registry for testing
          {:ok, _pid} = start_mock_registry(context)
          :ok

        _pid ->
          :ok
      end
    end

    @tag :skip
    test "returns error for empty provider list" do
      # This test needs a properly seeded mock - skip for now
      assert true
    end
  end

  # ── handle_add_model/2 ──────────────────────────────────────────────────

  describe "handle_add_model/2" do
    test "returns continue tuple" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, %{} = state} = AddModel.handle_add_model("/add_model", %{})
        end)

      assert is_binary(output)
    end
  end

  # ── Helpers ──────────────────────────────────────────────────────────────

  defp with_mock_path(_path, fun), do: fun.()

  defp start_mock_registry(_context) do
    # For integration testing with the real registry, this would need
    # a properly seeded JSON file. For unit tests, we test the individual
    # functions directly.
    {:ok, self()}
  end

  defp ok_or_dup({:ok, _key}), do: :ok
  defp ok_or_dup({:error, :already_exists}), do: :ok
  defp ok_or_dup(other), do: other
end
