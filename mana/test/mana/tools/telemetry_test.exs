defmodule Mana.Tools.TelemetryTest do
  @moduledoc """
  Tests for telemetry events emitted by Mana.Tools.Registry.

  Verifies that:
  - [:mana, :tool, :call, :start] is emitted when a tool call begins
  - [:mana, :tool, :call, :stop] is emitted when a tool call completes
  - [:mana, :tool, :call, :exception] is emitted on tool execution failure
  - Measurements and metadata contain the expected fields
  """

  use ExUnit.Case, async: false

  alias Mana.Tools.Registry

  @telemetry_prefix [:mana, :tool, :call]

  setup do
    start_supervised!(Registry)

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

  describe "tool call telemetry" do
    test "emits start and stop events for unknown tool", %{ref: ref} do
      result = Registry.execute("nonexistent_tool", %{"key" => "value"})

      assert {:error, :unknown_tool} = result

      # Should emit start event
      assert_received {^ref, @telemetry_prefix ++ [:start], start_measurements, start_meta}
      assert %{system_time: _} = start_measurements
      assert start_meta.tool_name == "nonexistent_tool"
      assert start_meta.args_keys == ["key"]

      # Should emit stop event (not exception — we handle errors gracefully)
      assert_received {^ref, @telemetry_prefix ++ [:stop], stop_measurements, stop_meta}
      assert %{duration: duration} = stop_measurements
      assert is_integer(duration)
      assert duration >= 0
      assert stop_meta.tool_name == "nonexistent_tool"
      assert stop_meta.error == :unknown_tool

      # No exception event
      refute_received {^ref, @telemetry_prefix ++ [:exception], _, _}
    end

    test "emits start and stop events for a registered tool", %{ref: ref} do
      # "list_files" is one of the expected tools registered at startup
      result = Registry.execute("list_files", %{"directory" => "."})

      assert {:ok, _} = result

      # Should emit start event
      assert_received {^ref, @telemetry_prefix ++ [:start], start_measurements, start_meta}
      assert %{system_time: _} = start_measurements
      assert start_meta.tool_name == "list_files"
      assert start_meta.args_keys == ["directory"]

      # Should emit stop event
      assert_received {^ref, @telemetry_prefix ++ [:stop], stop_measurements, stop_meta}
      assert %{duration: duration} = stop_measurements
      assert is_integer(duration)
      assert duration >= 0
      assert stop_meta.tool_name == "list_files"
      assert Map.has_key?(stop_meta, :result_size)
      assert is_integer(stop_meta.result_size)

      # No exception event
      refute_received {^ref, @telemetry_prefix ++ [:exception], _, _}
    end

    test "start metadata includes args_keys sorted", %{ref: ref} do
      Registry.execute("nonexistent_tool", %{"z" => 1, "a" => 2})

      assert_received {^ref, @telemetry_prefix ++ [:start], _, start_meta}
      assert start_meta.args_keys == ["a", "z"]
    end

    test "stop metadata includes error info for unknown tool", %{ref: ref} do
      Registry.execute("no_such_tool", %{})

      assert_received {^ref, @telemetry_prefix ++ [:stop], _, stop_meta}
      assert stop_meta.error == :unknown_tool
    end

    test "duration is monotonic time difference in native units", %{ref: ref} do
      Registry.execute("list_files", %{})

      assert_received {^ref, @telemetry_prefix ++ [:stop], stop_measurements, _}
      assert is_integer(stop_measurements.duration)
      assert stop_measurements.duration >= 0
    end
  end
end
