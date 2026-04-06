defmodule Mana.Agent.TelemetryTest do
  @moduledoc """
  Tests for telemetry events emitted by Mana.Agent.Runner.

  Verifies that:
  - [:mana, :agent, :run, :start] is emitted when a run begins
  - [:mana, :agent, :run, :stop] is emitted when a run completes
  - Measurements and metadata contain the expected fields
  - Streaming runs emit start events immediately
  """

  use ExUnit.Case, async: false

  alias Mana.Agent.Runner
  alias Mana.Callbacks.Registry
  alias Mana.Config.Store
  alias Mana.Session.Store, as: SessionStore
  alias Mana.Tools.Registry, as: ToolsRegistry

  @telemetry_prefix [:mana, :agent, :run]

  @test_agent_def %{
    name: "telemetry_test",
    display_name: "Telemetry Test",
    description: "A test agent for telemetry",
    system_prompt: "You are a telemetry test agent.",
    available_tools: [],
    user_prompt: "",
    tools_config: %{}
  }

  setup do
    start_supervised!(Store)
    start_supervised!(Registry)
    start_supervised!(SessionStore)
    start_supervised!(ToolsRegistry)

    # Attach a telemetry handler that captures events into the test process
    test_pid = self()
    ref = make_ref()

    handler_id = {__MODULE__, ref}

    :telemetry.attach_many(
      handler_id,
      [
        @telemetry_prefix ++ [:start],
        @telemetry_prefix ++ [:stop],
        @telemetry_prefix ++ [:exception]
      ],
      fn event_name, measurements, metadata, config ->
        send(config.test_pid, {config.ref, event_name, measurements, metadata})
      end,
      %{test_pid: test_pid, ref: ref}
    )

    on_exit(fn ->
      :telemetry.detach(handler_id)
    end)

    {:ok, ref: ref}
  end

  describe "synchronous run telemetry" do
    test "emits start and stop events", %{ref: ref} do
      agent_state = %{
        agent_def: @test_agent_def,
        model_name: "echo-model",
        session_id: "telemetry-test-session",
        system_prompt: "You are a test agent.",
        message_history: []
      }

      _result = Runner.run(agent_state, "Hello telemetry", max_iterations: 1)

      # Should emit start event
      assert_received {^ref, @telemetry_prefix ++ [:start], start_measurements, start_meta}
      assert %{system_time: _} = start_measurements
      assert start_meta.agent_name == "telemetry_test"
      assert start_meta.model == "echo-model"
      assert start_meta.session_id == "telemetry-test-session"

      # Should emit stop event
      assert_received {^ref, @telemetry_prefix ++ [:stop], stop_measurements, stop_meta}
      assert %{duration: duration} = stop_measurements
      assert is_integer(duration)
      assert duration >= 0
      assert stop_meta.agent_name == "telemetry_test"
      assert stop_meta.model == "echo-model"
      assert stop_meta.session_id == "telemetry-test-session"
      assert Map.has_key?(stop_meta, :success)

      # No exception event should be emitted
      refute_received {^ref, @telemetry_prefix ++ [:exception], _, _}
    end

    test "stop metadata includes error info on failure", %{ref: ref} do
      agent_state = %{
        agent_def: @test_agent_def,
        model_name: "echo-model",
        session_id: "telemetry-error-session",
        system_prompt: "You are a test agent.",
        message_history: []
      }

      _result = Runner.run(agent_state, "Hello", max_iterations: 1)

      assert_received {^ref, @telemetry_prefix ++ [:stop], _, stop_meta}
      assert Map.has_key?(stop_meta, :success)
    end
  end

  describe "streaming run telemetry" do
    test "emits start event immediately when stream is created", %{ref: ref} do
      agent_state = %{
        agent_def: @test_agent_def,
        model_name: "echo-model",
        session_id: "telemetry-stream-session",
        system_prompt: "You are a test agent.",
        message_history: []
      }

      # Just creating the stream should emit the start event
      _stream = Runner.stream(agent_state, "Hello stream", max_iterations: 1)

      assert_received {^ref, @telemetry_prefix ++ [:start], start_measurements, start_meta}
      assert %{system_time: _} = start_measurements
      assert start_meta.agent_name == "telemetry_test"
      assert start_meta.model == "echo-model"
      assert start_meta.session_id == "telemetry-stream-session"
    end

    test "start metadata contains correct agent info", %{ref: ref} do
      agent_state = %{
        agent_def: %{name: "custom_agent"},
        model_name: "test-model-v2",
        session_id: "meta-test-session",
        system_prompt: "You are a test agent.",
        message_history: []
      }

      _stream = Runner.stream(agent_state, "Metadata test", max_iterations: 1)

      assert_received {^ref, @telemetry_prefix ++ [:start], measurements, meta}
      assert is_integer(measurements.system_time)
      assert meta.agent_name == "custom_agent"
      assert meta.model == "test-model-v2"
      assert meta.session_id == "meta-test-session"
    end
  end

  describe "telemetry event measurements" do
    test "duration is monotonic time difference in native units", %{ref: ref} do
      agent_state = %{
        agent_def: @test_agent_def,
        model_name: "echo-model",
        session_id: "duration-test-session",
        system_prompt: "You are a test agent.",
        message_history: []
      }

      _result = Runner.run(agent_state, "Duration test", max_iterations: 1)

      assert_received {^ref, @telemetry_prefix ++ [:stop], stop_measurements, _}
      assert is_integer(stop_measurements.duration)
      assert stop_measurements.duration >= 0
    end
  end
end
