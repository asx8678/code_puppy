defmodule CodePuppyControl.CLI.SlashCommands.Commands.ModelSettingsTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.CLI.SlashCommands.{CommandInfo, Dispatcher, Registry}
  alias CodePuppyControl.CLI.SlashCommands.Commands.ModelSettings
  alias CodePuppyControl.Config.Models

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

  # ── --show with no model name (uses global model) ─────────────────────────

  describe "/model_settings --show (no model name)" do
    test "shows settings header with global model name" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/model_settings --show", %{})
        end)

      # Should mention the global model name from the config
      global_model = Models.global_model_name()
      assert output =~ global_model
    end

    test "indicates no custom settings when none configured" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/model_settings --show", %{})
        end)

      # With no settings configured, should show "no custom settings" message
      assert output =~ "No custom settings configured" or output =~ "using model defaults"
    end
  end

  # ── --show with a specific model name ─────────────────────────────────────

  describe "/model_settings --show <model_name>" do
    test "shows settings header with specified model name" do
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

      assert output =~ "No custom settings configured"
    end

    test "shows configured settings for a model" do
      # Write a setting directly via the config system
      Models.set_model_setting("gpt-5", "temperature", 0.7)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} =
                   ModelSettings.handle_model_settings(
                     "/model_settings --show gpt-5",
                     %{}
                   )
        end)

      assert output =~ "Settings for"
      assert output =~ "Temperature"

      # Cleanup
      Models.set_model_setting("gpt-5", "temperature", nil)
    end

    test "shows multiple settings when configured" do
      Models.set_model_setting("test-model-ms", "temperature", 0.5)
      Models.set_model_setting("test-model-ms", "seed", 42)
      Models.set_model_setting("test-model-ms", "top_p", 0.9)

      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} =
                   ModelSettings.handle_model_settings(
                     "/model_settings --show test-model-ms",
                     %{}
                   )
        end)

      assert output =~ "Temperature"
      assert output =~ "Seed"
      assert output =~ "Top-P"

      # Cleanup
      Models.set_model_setting("test-model-ms", "temperature", nil)
      Models.set_model_setting("test-model-ms", "seed", nil)
      Models.set_model_setting("test-model-ms", "top_p", nil)
    end
  end

  # ── /ms alias ─────────────────────────────────────────────────────────────

  describe "/ms alias" do
    test "/ms --show works like /model_settings --show" do
      output =
        ExUnit.CaptureIO.capture_io(fn ->
          assert {:continue, _} = ModelSettings.handle_model_settings("/ms --show", %{})
        end)

      # Should show the global model name
      global_model = Models.global_model_name()
      assert output =~ global_model
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
      # Models like "gpt-4.1-mini" have dots and hyphens
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
end
