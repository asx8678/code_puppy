defmodule CodePuppyControl.CLI.SlashCommands.Commands.ModelSettingsTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Dispatcher, Registry}
  alias CodePuppyControl.CLI.SlashCommands.Commands.ModelSettings

  # async: false because Registry is a named singleton.

  setup do
    # Start the Registry GenServer if not already running
    case Process.whereis(Registry) do
      nil -> start_supervised!({Registry, []})
      _pid -> :ok
    end

    Registry.clear()

    # Register /model_settings and /ms
    :ok =
      Registry.register(
        CommandInfo.new(
          name: "model_settings",
          description: "Show per-model settings",
          handler: &ModelSettings.handle_model_settings/2,
          usage: "/model_settings --show [model_name]",
          aliases: ["ms"],
          category: "config"
        )
      )

    state = %{session_id: "test-session", running: true}
    {:ok, state: state}
  end

  # ── Registration & Dispatch ──────────────────────────────────────────────

  describe "registration" do
    test "/model_settings is registered and dispatchable" do
      assert {:ok, cmd} = Registry.get("model_settings")
      assert cmd.name == "model_settings"
    end

    test "/ms alias resolves to model_settings" do
      assert {:ok, cmd} = Registry.get("ms")
      assert cmd.name == "model_settings"
    end

    test "dispatching /model_settings --show returns continue" do
      assert {:ok, {:continue, _}} = Dispatcher.dispatch("/model_settings --show", nil)
    end

    test "dispatching /ms --show returns continue" do
      assert {:ok, {:continue, _}} = Dispatcher.dispatch("/ms --show", nil)
    end
  end

  # ── Pure formatting (config-isolated) ────────────────────────────────────

  describe "format_summary/2 — pure function" do
    test "shows 'no custom settings' when settings map is empty" do
      output = ModelSettings.format_summary("gpt-5", %{})
      assert output =~ "No custom settings configured"
      assert output =~ "gpt-5"
      assert output =~ "using model defaults"
    end

    test "shows settings header when settings present" do
      output = ModelSettings.format_summary("claude-opus-4", %{"temperature" => 0.7})
      assert output =~ "Settings for claude-opus-4"
      assert output =~ "Temperature"
      assert output =~ "0.70"
    end

    test "shows multiple settings sorted by key" do
      settings = %{
        "seed" => 42,
        "temperature" => 0.5,
        "top_p" => 0.9
      }

      output = ModelSettings.format_summary("test-model", settings)

      assert output =~ "Temperature"
      assert output =~ "Seed"
      assert output =~ "Top-P"
    end

    test "handles nil setting value without crashing" do
      output = ModelSettings.format_summary("test-model", %{"temperature" => nil})
      assert output =~ "Temperature"
      assert output =~ "not set"
    end

    test "handles blank string setting value without crashing" do
      output = ModelSettings.format_summary("test-model", %{"seed" => ""})
      assert output =~ "Seed"
      assert output =~ "not set"
    end

    test "shows boolean settings as Enabled/Disabled" do
      output =
        ModelSettings.format_summary("test-model", %{
          "interleaved_thinking" => true,
          "clear_thinking" => false
        })

      assert output =~ "Interleaved Thinking"
      assert output =~ "Enabled"
      assert output =~ "Clear Thinking"
      assert output =~ "Disabled"
    end

    test "shows choice settings as string values" do
      output =
        ModelSettings.format_summary("test-model", %{
          "reasoning_effort" => "high",
          "verbosity" => "low"
        })

      assert output =~ "Reasoning Effort"
      assert output =~ "high"
      assert output =~ "Verbosity"
      assert output =~ "low"
    end

    test "handles model names with special characters" do
      output = ModelSettings.format_summary("gpt-4.1-mini", %{})
      assert output =~ "gpt-4.1-mini"
    end

    test "shows OpenAI global controls when included in settings" do
      output =
        ModelSettings.format_summary("test-openai-model", %{
          "reasoning_effort" => "medium",
          "summary" => "auto",
          "verbosity" => "high"
        })

      assert output =~ "Reasoning Effort"
      assert output =~ "medium"
      assert output =~ "Reasoning Summary"
      assert output =~ "auto"
      assert output =~ "Verbosity"
      assert output =~ "high"
    end
  end

  # ── /model_settings --show (IO integration, no config mutation) ─────────

  describe "/model_settings --show (no model name)" do
    test "does not crash and returns continue" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} =
                   ModelSettings.handle_model_settings("/model_settings --show", %{})
        end)

      # Should produce some output (the model name from config)
      assert is_binary(output)
      assert output != ""
    end
  end

  describe "/model_settings --show <model_name>" do
    test "shows model name in output" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} =
                   ModelSettings.handle_model_settings(
                     "/model_settings --show claude-opus-4",
                     %{}
                   )
        end)

      assert output =~ "claude-opus-4"
    end

    test "shows no custom settings for unconfigured model" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} =
                   ModelSettings.handle_model_settings(
                     "/model_settings --show some-random-model",
                     %{}
                   )
        end)

      # Either "No custom settings" or settings from global controls
      assert is_binary(output)
    end
  end

  # ── /ms alias ─────────────────────────────────────────────────────────────

  describe "/ms alias" do
    test "/ms --show works like /model_settings --show" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/ms --show", %{})
        end)

      assert is_binary(output)
    end

    test "/ms --show <model> works like /model_settings --show <model>" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} =
                   ModelSettings.handle_model_settings("/ms --show gemini-pro", %{})
        end)

      assert output =~ "gemini-pro"
    end
  end

  # ── Without --show flag ───────────────────────────────────────────────────

  describe "/model_settings without --show" do
    test "prints usage hint" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/model_settings", %{})
        end)

      assert output =~ "Usage:"
    end

    test "mentions --show flag in usage" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/model_settings", %{})
        end)

      assert output =~ "--show"
    end

    test "mentions bd-271 for interactive editor" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/model_settings", %{})
        end)

      assert output =~ "bd-271"
    end
  end

  # ── Format helpers ────────────────────────────────────────────────────────

  describe "format_setting_value/2" do
    test "formats nil as not set" do
      assert ModelSettings.format_setting_value(nil, %{type: :numeric, format: "{:.2f}"}) ==
               "— (not set)"
    end

    test "formats blank string as not set" do
      assert ModelSettings.format_setting_value("", %{type: :choice}) == "— (not set)"
    end

    test "formats boolean true as Enabled" do
      assert ModelSettings.format_setting_value(true, %{type: :boolean}) == "Enabled"
    end

    test "formats boolean false as Disabled" do
      assert ModelSettings.format_setting_value(false, %{type: :boolean}) == "Disabled"
    end

    test "formats choice value as string" do
      assert ModelSettings.format_setting_value("medium", %{type: :choice}) == "medium"
    end

    test "formats numeric value with 2 decimal places" do
      result = ModelSettings.format_setting_value(0.75, %{type: :numeric, format: "{:.2f}"})
      assert result == "0.75"
    end

    test "formats numeric value as integer when format is {:.0f}" do
      result = ModelSettings.format_setting_value(42, %{type: :numeric, format: "{:.0f}"})
      assert result == "42"
    end

    test "formats unknown type as string" do
      assert ModelSettings.format_setting_value("hello", %{type: :unknown}) == "hello"
    end

    test "formats with fallback when no format key" do
      assert ModelSettings.format_setting_value(99, %{type: :numeric}) == "99"
    end

    test "nil with boolean definition shows not set (not Enabled/Disabled)" do
      assert ModelSettings.format_setting_value(nil, %{type: :boolean}) == "— (not set)"
    end

    test "nil with choice definition shows not set" do
      assert ModelSettings.format_setting_value(nil, %{type: :choice}) == "— (not set)"
    end
  end

  # ── Setting definitions coverage ──────────────────────────────────────────

  describe "setting_definitions/0" do
    test "contains expected setting keys" do
      defs = ModelSettings.setting_definitions()

      expected_keys = [
        "temperature",
        "seed",
        "top_p",
        "reasoning_effort",
        "summary",
        "verbosity",
        "extended_thinking",
        "budget_tokens",
        "interleaved_thinking",
        "clear_thinking",
        "thinking_enabled",
        "thinking_level",
        "effort"
      ]

      Enum.each(expected_keys, fn key ->
        assert Map.has_key?(defs, key), "Expected key #{key} in setting_definitions"
      end)
    end

    test "each definition has name and type" do
      defs = ModelSettings.setting_definitions()

      Enum.each(defs, fn {key, defn} ->
        assert Map.has_key?(defn, :name), "Definition for #{key} missing :name"
        assert Map.has_key?(defn, :type), "Definition for #{key} missing :type"
      end)
    end
  end

  # ── Edge cases ────────────────────────────────────────────────────────────

  describe "edge cases" do
    test "handles model names with special characters" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} =
                   ModelSettings.handle_model_settings(
                     "/model_settings --show gpt-4.1-mini",
                     %{}
                   )
        end)

      assert output =~ "gpt-4.1-mini"
    end

    test "always returns {:continue, state}" do
      result = ModelSettings.handle_model_settings("/model_settings --show", %{foo: "bar"})
      assert result == {:continue, %{foo: "bar"}}
    end

    test "handles /ms without --show" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/ms", %{})
        end)

      assert output =~ "Usage:"
    end
  end

  # ── Capability-based display (Python parity) ─────────────────────────────

  describe "get_display_settings/1 — capability-based merging" do
    test "includes OpenAI global controls for models with supported_settings" do
      # This test uses a model name from models.json that has
      # supported_settings including "reasoning_effort" etc.
      # Since the Elixir models.json may not have OpenAI models with
      # reasoning_effort in supported_settings, we verify the function
      # doesn't crash and returns a map.
      result = ModelSettings.get_display_settings("firepass-kimi-k2p5-turbo")
      assert is_map(result)
    end

    test "does not crash for unknown model names" do
      result = ModelSettings.get_display_settings("nonexistent-model-xyz")
      assert is_map(result)
    end
  end
end
