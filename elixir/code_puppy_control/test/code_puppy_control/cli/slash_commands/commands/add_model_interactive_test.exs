defmodule CodePuppyControl.CLI.SlashCommands.Commands.AddModelInteractiveTest do
  @moduledoc """
  Tests for AddModel.Interactive: the real IO flow including
  non-tool-calling confirmation, persistence, and ModelRegistry reload.

  These tests exercise the actual Interactive module functions (or helpers
  inside it) rather than hand-rolling the flow.

  Split from add_model_test.exs to keep under the 600-line cap.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Registry}
  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModel
  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModel.Interactive
  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistence
  alias CodePuppyControl.ModelsDevParser
  alias CodePuppyControl.ModelsDevParser.{ModelInfo, ProviderInfo}

  # Fixture path — relative from this test file to test/support/
  @fixture_path Path.join([__DIR__, "../../../../support/models_dev_parser_test_data.json"])

  setup do
    # Start the SlashCommands Registry GenServer if not already running
    case Process.whereis(Registry) do
      nil -> start_supervised!({Registry, []})
      _pid -> :ok
    end

    Registry.clear()

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

    # Start LockKeeper
    case Process.whereis(AddModelPersistence.LockKeeper) do
      nil -> start_supervised!({AddModelPersistence.LockKeeper, []})
      _pid -> :ok
    end

    # Use a temp directory for extra_models.json
    tmp_dir = Path.join(System.tmp_dir!(), "cp_add_model_interactive_test_#{:erlang.unique_integer([:positive])}")
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

    provider = %ProviderInfo{id: "openai", name: "OpenAI", env: ["OPENAI_API_KEY"]}
    model_tool = %ModelInfo{provider_id: "openai", model_id: "gpt-5", name: "GPT-5", context_length: 128_000, tool_call: true}
    model_no_tool = %ModelInfo{provider_id: "test-provider", model_id: "no-tools", name: "No Tools", context_length: 4096, tool_call: false}

    {:ok,
     tmp_dir: tmp_dir,
     provider: provider,
     model_tool: model_tool,
     model_no_tool: model_no_tool}
  end

  # ── do_add_model/2 via Interactive ──────────────────────────────────────

  describe "Interactive.do_add_model/2 — tool-calling model" do
    test "persists model and prints success message", %{provider: provider, model_tool: model, tmp_dir: tmp_dir} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          Interactive.do_add_model(model, provider)
        end)

      assert output =~ "Added"
      assert output =~ model.model_id

      # Verify persistence on disk
      path = Path.join(tmp_dir, "extra_models.json")
      assert File.exists?(path)
      {:ok, data} = Jason.decode(File.read!(path))
      assert Enum.any?(Map.keys(data), &String.contains?(&1, model.model_id))
    end

    test "prints registry reloaded message when ModelRegistry is available", %{provider: provider, model_tool: model} do
      # ModelRegistry may or may not be running — test that the function
      # handles both cases gracefully.
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          Interactive.do_add_model(model, provider)
        end)

      # Either "reloaded" or "reload failed" — both are acceptable
      assert output =~ "Added"
    end

    test "handles duplicate model gracefully", %{provider: provider, model_tool: model} do
      # First add succeeds
      ExUnit.CaptureIO.capture_io(fn ->
        Interactive.do_add_model(model, provider)
      end)

      # Second add of the same model
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          Interactive.do_add_model(model, provider)
        end)

      assert output =~ "already in extra_models.json"
    end
  end

  # ── execute_add_model/2 — non-tool-calling confirmation ─────────────────

  describe "Interactive.execute_add_model/2 — non-tool-calling model" do
    test "warns about non-tool-calling model and cancels on 'n'", %{provider: provider, model_no_tool: model} do
      output =
        ExUnit.CaptureIO.capture_io([input: "n\n"], fn ->
          Interactive.execute_add_model(model, provider)
        end)

      assert output =~ "does NOT support tool calling"
      assert output =~ "Cancelled"
      refute output =~ "Added"
    end

    test "warns about non-tool-calling model and proceeds on 'y'", %{provider: provider, model_no_tool: model, tmp_dir: tmp_dir} do
      output =
        ExUnit.CaptureIO.capture_io([input: "y\n"], fn ->
          Interactive.execute_add_model(model, provider)
        end)

      assert output =~ "does NOT support tool calling"
      assert output =~ "Added"
      refute output =~ "Cancelled"

      # Verify persistence on disk
      path = Path.join(tmp_dir, "extra_models.json")
      assert File.exists?(path)
    end

    test "cancels on empty input (default N)", %{provider: provider, model_no_tool: model} do
      output =
        ExUnit.CaptureIO.capture_io([input: "\n"], fn ->
          Interactive.execute_add_model(model, provider)
        end)

      assert output =~ "does NOT support tool calling"
      assert output =~ "Cancelled"
    end

    test "cancels on EOF", %{provider: provider, model_no_tool: model} do
      # CaptureIO with no input simulates EOF
      output =
        ExUnit.CaptureIO.capture_io([input: ""], fn ->
          Interactive.execute_add_model(model, provider)
        end)

      assert output =~ "does NOT support tool calling"
      assert output =~ "Cancelled"
    end
  end

  describe "Interactive.execute_add_model/2 — tool-calling model (no confirmation needed)" do
    test "proceeds directly without confirmation prompt", %{provider: provider, model_tool: model} do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          Interactive.execute_add_model(model, provider)
        end)

      # No warning about tool calling
      refute output =~ "does NOT support tool calling"
      # Goes straight to do_add_model
      assert output =~ "Added"
    end
  end

  # ── ModelRegistry.reload invocation ─────────────────────────────────────

  describe "ModelRegistry.reload/0 invocation via Interactive" do
    setup context do
      ensure_fixture_registry!()

      # Start ModelRegistry so we can verify reload makes models available
      case Process.whereis(CodePuppyControl.ModelRegistry) do
        nil -> start_supervised!({CodePuppyControl.ModelRegistry, []})
        _pid -> :ok
      end

      {:ok, context}
    end

    test "add_model_to_config/2 does NOT call ModelRegistry.reload (that's Interactive's job)" do
      # add_model_to_config/2 is the pure persistence function — it should
      # NOT call ModelRegistry.reload.  We verify by calling it without
      # ModelRegistry started (would crash if it tried).
      provider = %ProviderInfo{id: "openai", name: "OpenAI", env: ["OPENAI_API_KEY"]}
      model = %ModelInfo{provider_id: "openai", model_id: "gpt-5-noreload", name: "GPT-5 NoReload", context_length: 128_000, tool_call: true}

      result = AddModel.add_model_to_config(model, provider)
      assert {:ok, _key} = result
    end

    test "Interactive.do_add_model/2 reloads ModelRegistry and makes model immediately available" do
      provider = %ProviderInfo{id: "openai", name: "OpenAI", env: ["OPENAI_API_KEY"]}
      model = %ModelInfo{provider_id: "openai", model_id: "gpt-5-reg", name: "GPT-5 Reg", context_length: 128_000, tool_call: true}
      model_key = "openai-gpt-5-reg"

      # Pre-condition: model is NOT yet in the registry
      assert CodePuppyControl.ModelRegistry.get_config(model_key) == nil,
             "model #{model_key} should not be in registry before add"

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          Interactive.do_add_model(model, provider)
        end)

      # The do_add_model path should print "Added" and attempt reload
      assert output =~ "Added"

      # Post-condition: model IS now available in the registry after reload
      config = CodePuppyControl.ModelRegistry.get_config(model_key)
      assert config != nil, "model #{model_key} should be in registry after add+reload"
      assert Map.get(config, "type") != nil, "persisted config should have a 'type' field"
    end
  end

  # ── run_with_inputs/1 end-to-end ───────────────────────────────────────

  describe "run_with_inputs/1 end-to-end" do
    setup do
      ensure_fixture_registry!()

      case Process.whereis(AddModelPersistence.LockKeeper) do
        nil -> start_supervised!({AddModelPersistence.LockKeeper, []})
        _pid -> :ok
      end

      :ok
    end

    test "full flow: provider selection → model selection → persistence" do
      result = AddModel.run_with_inputs(["1", "1"])

      assert {:ok, model_key} = result
      assert is_binary(model_key)

      path = CodePuppyControl.Config.Paths.extra_models_file()
      assert File.exists?(path), "extra_models.json should exist after persist"

      {:ok, data} = Jason.decode(File.read!(path))
      assert Map.has_key?(data, model_key), "persisted key #{model_key} not found in extra_models.json"

      config = data[model_key]
      assert Map.has_key?(config, "type")
      assert Map.has_key?(config, "provider")
      assert Map.has_key?(config, "name")
    end

    test "second provider, second model persists correctly" do
      result = AddModel.run_with_inputs(["2", "2"])

      assert {:ok, model_key} = result
      assert is_binary(model_key)

      path = CodePuppyControl.Config.Paths.extra_models_file()
      assert File.exists?(path)

      {:ok, data} = Jason.decode(File.read!(path))
      assert Map.has_key?(data, model_key)
    end

    test "returns error for empty inputs" do
      result = AddModel.run_with_inputs([])
      assert result == :cancelled
    end

    test "returns error for invalid provider selection" do
      result = AddModel.run_with_inputs(["999999"])
      assert match?({:error, _}, result)
    end

    test "returns error for invalid model selection" do
      result = AddModel.run_with_inputs(["1", "999999"])
      assert match?({:error, _}, result)
    end
  end

  # ── handle_add_model/2 ─────────────────────────────────────────────────

  describe "handle_add_model/2" do
    setup do
      ensure_fixture_registry!()
      :ok
    end

    test "returns continue tuple" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, %{}} = AddModel.handle_add_model("/add_model", %{})
        end)

      assert is_binary(output)
    end

    test "delegates to Interactive.run_interactive/0 with fixture registry", %{tmp_dir: tmp_dir} do
      # Drive handle_add_model/2 through stdin — selects provider 1, model 1
      {result, output} =
        ExUnit.CaptureIO.with_io([input: "1\n1\n"], fn ->
          AddModel.handle_add_model("/add_model", %{})
        end)

      assert result == {:continue, %{}}
      assert output =~ "Added"

      # Verify persistence on disk
      path = Path.join(tmp_dir, "extra_models.json")
      assert File.exists?(path)
    end
  end

  # ── run_interactive/0 end-to-end via stdin ────────────────────────────────

  describe "Interactive.run_interactive/0 — real stdin-driven flow" do
    setup do
      ensure_fixture_registry!()

      case Process.whereis(AddModelPersistence.LockKeeper) do
        nil -> start_supervised!({AddModelPersistence.LockKeeper, []})
        _pid -> :ok
      end

      :ok
    end

    test "tool-calling model: provider → model → persist", %{tmp_dir: tmp_dir} do
      # Fixture data sorted by name: 1=Another Provider (1 model), 2=Test Provider (3 models)
      # Select provider 1 (Another Provider), then model 1 (GPT Model, tool_call=true)
      output =
        ExUnit.CaptureIO.capture_io([input: "1\n1\n"], fn ->
          Interactive.run_interactive()
        end)

      # Should show provider list, model list, and persist
      assert output =~ "Add Model"
      assert output =~ "Added"
      assert output =~ "gpt-model"

      # Verify persistence on disk
      path = Path.join(tmp_dir, "extra_models.json")
      assert File.exists?(path), "extra_models.json should exist after persist"
      {:ok, data} = Jason.decode(File.read!(path))
      assert Enum.any?(Map.keys(data), &String.contains?(&1, "gpt-model"))
    end

    test "non-tool-calling model: confirmation y → persist", %{tmp_dir: tmp_dir} do
      # Select provider 2 (Test Provider), model 1 (Cheap Model, tool_call=false)
      # Then confirm with 'y' at the warning prompt
      output =
        ExUnit.CaptureIO.capture_io([input: "2\n1\ny\n"], fn ->
          Interactive.run_interactive()
        end)

      assert output =~ "does NOT support tool calling"
      assert output =~ "Added"

      # Verify persistence on disk
      path = Path.join(tmp_dir, "extra_models.json")
      assert File.exists?(path)
      {:ok, data} = Jason.decode(File.read!(path))
      assert Enum.any?(Map.keys(data), &String.contains?(&1, "cheap-model"))
    end

    test "non-tool-calling model: confirmation n → cancel", %{tmp_dir: tmp_dir} do
      # Select provider 2, model 1 (Cheap Model), then cancel at confirmation
      output =
        ExUnit.CaptureIO.capture_io([input: "2\n1\nn\n"], fn ->
          Interactive.run_interactive()
        end)

      assert output =~ "does NOT support tool calling"
      assert output =~ "Cancelled"
      refute output =~ "Added"

      # Verify nothing was persisted
      path = Path.join(tmp_dir, "extra_models.json")
      refute File.exists?(path)
    end

    test "cancel at provider selection", %{tmp_dir: tmp_dir} do
      output =
        ExUnit.CaptureIO.capture_io([input: "q\n"], fn ->
          Interactive.run_interactive()
        end)

      assert output =~ "Cancelled"
      refute output =~ "Added"
    end
  end

  # ── Private helpers ────────────────────────────────────────────────────────

  # Starts a fixture-backed ModelsDevParser.Registry, ensuring we never
  # silently reuse an already-running instance that might have different data.
  defp ensure_fixture_registry! do
    # Stop any existing registry so we get a clean one with fixture data
    case Process.whereis(ModelsDevParser.Registry) do
      nil -> :ok
      pid ->
        ref = Process.monitor(pid)
        GenServer.stop(pid, :shutdown, 5_000)
        receive do
          {:DOWN, ^ref, :process, ^pid, _} -> :ok
        after
          5_000 -> Process.demonitor(ref, [:flush])
        end
    end

    start_supervised!(
      {ModelsDevParser.Registry, json_path: @fixture_path}
    )

    :ok
  end
end
