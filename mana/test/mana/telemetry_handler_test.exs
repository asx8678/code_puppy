defmodule Mana.TelemetryHandlerTest do
  @moduledoc """
  Tests for Mana.TelemetryHandler.

  Verifies that the handler correctly aggregates metrics from
  agent, tool, and model telemetry events into ETS counters.
  """

  use ExUnit.Case, async: false

  alias Mana.TelemetryHandler

  setup do
    TelemetryHandler.reset()
    TelemetryHandler.attach()

    on_exit(fn ->
      TelemetryHandler.reset()
    end)

    :ok
  end

  describe "attach/0" do
    test "can be called multiple times without error" do
      TelemetryHandler.attach()
      TelemetryHandler.attach()
    end
  end

  describe "agent events" do
    test "tracks agent run stop with success" do
      :telemetry.execute(
        [:mana, :agent, :run, :stop],
        %{duration: 1_000_000},
        %{agent_name: "test_agent", model: "test-model", session_id: "s1", success: true}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.agents.count == 1
      assert stats.agents.success_count == 1
      assert stats.agents.error_count == 0
    end

    test "tracks agent run stop with failure" do
      :telemetry.execute(
        [:mana, :agent, :run, :stop],
        %{duration: 500_000},
        %{agent_name: "test_agent", model: "test-model", session_id: "s1", success: false}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.agents.count == 1
      assert stats.agents.error_count == 1
      assert stats.agents.success_count == 0
    end

    test "tracks agent run exception" do
      :telemetry.execute(
        [:mana, :agent, :run, :exception],
        %{duration: 100_000},
        %{agent_name: "test_agent", model: "test-model", session_id: "s1", kind: :error, reason: :boom}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.agents.count == 1
      assert stats.agents.error_count == 1
    end

    test "accumulates multiple agent runs" do
      for _ <- 1..5 do
        :telemetry.execute(
          [:mana, :agent, :run, :stop],
          %{duration: 1_000_000},
          %{agent_name: "a", model: "m", session_id: "s", success: true}
        )
      end

      assert TelemetryHandler.get_stats().agents.count == 5
      assert TelemetryHandler.get_stats().agents.success_count == 5
    end
  end

  describe "tool events" do
    test "tracks tool call stop with success" do
      :telemetry.execute(
        [:mana, :tool, :call, :stop],
        %{duration: 500_000},
        %{tool_name: "list_files", result_size: 1024}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.tools.count == 1
      assert stats.tools.error_count == 0
      assert Map.has_key?(stats.tools.by_tool, "list_files")
      assert stats.tools.by_tool["list_files"].count == 1
    end

    test "tracks tool call stop with error" do
      :telemetry.execute(
        [:mana, :tool, :call, :stop],
        %{duration: 100_000},
        %{tool_name: "bad_tool", error: :unknown_tool}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.tools.count == 1
      assert stats.tools.error_count == 1
      assert stats.tools.by_tool["bad_tool"].error_count == 1
    end

    test "tracks tool call exception" do
      :telemetry.execute(
        [:mana, :tool, :call, :exception],
        %{duration: 50_000},
        %{tool_name: "crashy_tool", kind: :error, reason: :timeout}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.tools.count == 1
      assert stats.tools.error_count == 1
    end

    test "aggregates per-tool stats" do
      :telemetry.execute([:mana, :tool, :call, :stop], %{duration: 100}, %{tool_name: "tool_a"})
      :telemetry.execute([:mana, :tool, :call, :stop], %{duration: 200}, %{tool_name: "tool_a"})
      :telemetry.execute([:mana, :tool, :call, :stop], %{duration: 300}, %{tool_name: "tool_b"})

      stats = TelemetryHandler.get_stats()

      assert stats.tools.by_tool["tool_a"].count == 2
      assert stats.tools.by_tool["tool_b"].count == 1
    end
  end

  describe "model events" do
    test "tracks model request stop with success" do
      :telemetry.execute(
        [:mana, :model, :request, :stop],
        %{duration: 2_000_000},
        %{provider: "anthropic", model_name: "claude-3-sonnet", tokens_in: 100, tokens_out: 50}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.models.count == 1
      assert stats.models.total_tokens_in == 100
      assert stats.models.total_tokens_out == 50
      assert stats.models.error_count == 0
      assert Map.has_key?(stats.models.by_provider, "anthropic")
      assert stats.models.by_provider["anthropic"].count == 1
    end

    test "tracks model request stop with error" do
      :telemetry.execute(
        [:mana, :model, :request, :stop],
        %{duration: 500_000},
        %{provider: "openai", model_name: "gpt-4", error_type: :authentication_error}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.models.count == 1
      assert stats.models.error_count == 1
      assert stats.models.by_provider["openai"].error_count == 1
    end

    test "tracks model request exception" do
      :telemetry.execute(
        [:mana, :model, :request, :exception],
        %{duration: 100_000},
        %{provider: "openai", model_name: "gpt-4", kind: :error, reason: :timeout}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.models.count == 1
      assert stats.models.error_count == 1
    end

    test "aggregates per-provider stats" do
      :telemetry.execute(
        [:mana, :model, :request, :stop],
        %{duration: 1_000_000},
        %{provider: "anthropic", model_name: "claude-3", tokens_in: 50, tokens_out: 25}
      )

      :telemetry.execute(
        [:mana, :model, :request, :stop],
        %{duration: 2_000_000},
        %{provider: "openai", model_name: "gpt-4", tokens_in: 100, tokens_out: 75}
      )

      stats = TelemetryHandler.get_stats()

      assert stats.models.by_provider["anthropic"].total_tokens_in == 50
      assert stats.models.by_provider["openai"].total_tokens_in == 100
    end
  end

  describe "reset/0" do
    test "clears all counters" do
      :telemetry.execute(
        [:mana, :agent, :run, :stop],
        %{duration: 1_000},
        %{agent_name: "a", model: "m", session_id: "s", success: true}
      )

      assert TelemetryHandler.get_stats().agents.count == 1

      TelemetryHandler.reset()

      assert TelemetryHandler.get_stats().agents.count == 0
    end
  end

  describe "get_stats/0" do
    test "returns zero defaults when no events fired" do
      stats = TelemetryHandler.get_stats()

      assert stats.agents.count == 0
      assert stats.tools.count == 0
      assert stats.models.count == 0
      assert stats.tools.by_tool == %{}
      assert stats.models.by_provider == %{}
    end
  end
end
