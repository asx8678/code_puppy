defmodule Mana.Models.TelemetryTest do
  @moduledoc """
  Tests for telemetry events emitted by model providers.

  Verifies that:
  - [:mana, :model, :request, :start] is emitted when an API request begins
  - [:mana, :model, :request, :stop] is emitted when an API request completes
  - Measurements and metadata contain the expected fields
  """

  use ExUnit.Case, async: false

  alias Mana.Models.Providers.Anthropic
  alias Mana.Models.Providers.OpenAI

  @telemetry_prefix [:mana, :model, :request]

  setup do
    # Clear environment variables for clean tests
    original_anthropic = System.get_env("ANTHROPIC_API_KEY")
    original_openai = System.get_env("OPENAI_API_KEY")
    System.delete_env("ANTHROPIC_API_KEY")
    System.delete_env("OPENAI_API_KEY")

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

      if original_anthropic, do: System.put_env("ANTHROPIC_API_KEY", original_anthropic)
      if original_openai, do: System.put_env("OPENAI_API_KEY", original_openai)
    end)

    {:ok, ref: ref}
  end

  describe "Anthropic telemetry" do
    test "emits start and stop events on API error", %{ref: ref} do
      result =
        Anthropic.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "claude-3-sonnet",
          api_key: "invalid-key"
        )

      assert {:error, _} = result

      # Should emit start event
      assert_received {^ref, @telemetry_prefix ++ [:start], start_measurements, start_meta}
      assert %{system_time: _} = start_measurements
      assert start_meta.provider == "anthropic"
      assert start_meta.model_name == "claude-3-sonnet"
      assert is_integer(start_meta.estimated_tokens)

      # Should emit stop event
      assert_received {^ref, @telemetry_prefix ++ [:stop], stop_measurements, stop_meta}
      assert %{duration: duration} = stop_measurements
      assert is_integer(duration)
      assert duration >= 0
      assert Map.has_key?(stop_meta, :error_type)

      # No exception event — errors are handled gracefully
      refute_received {^ref, @telemetry_prefix ++ [:exception], _, _}
    end

    test "does not emit telemetry when config validation fails" do
      # No API key → validate_config fails before telemetry span
      result = Anthropic.complete([%{"role" => "user", "content" => "Hello"}], "claude-3-sonnet")

      assert {:error, _} = result

      # Should NOT emit any telemetry events
      refute_received {_, @telemetry_prefix ++ [:start], _, _}
      refute_received {_, @telemetry_prefix ++ [:stop], _, _}
    end

    test "start metadata includes estimated_tokens based on message content", %{ref: ref} do
      long_content = String.duplicate("hello ", 100)

      _result =
        Anthropic.complete(
          [%{"role" => "user", "content" => long_content}],
          "claude-3-sonnet",
          api_key: "test-key"
        )

      assert_received {^ref, @telemetry_prefix ++ [:start], _, start_meta}
      # "hello " is 6 chars × 100 = 600 chars / 4 = ~150 tokens
      assert start_meta.estimated_tokens >= 100
    end
  end

  describe "OpenAI telemetry" do
    test "emits start and stop events on API error", %{ref: ref} do
      result =
        OpenAI.complete(
          [%{"role" => "user", "content" => "Hello"}],
          "gpt-4",
          api_key: "invalid-key"
        )

      assert {:error, _} = result

      # Should emit start event
      assert_received {^ref, @telemetry_prefix ++ [:start], start_measurements, start_meta}
      assert %{system_time: _} = start_measurements
      assert start_meta.provider == "openai"
      assert start_meta.model_name == "gpt-4"
      assert is_integer(start_meta.estimated_tokens)

      # Should emit stop event
      assert_received {^ref, @telemetry_prefix ++ [:stop], stop_measurements, stop_meta}
      assert %{duration: duration} = stop_measurements
      assert is_integer(duration)
      assert duration >= 0
      assert Map.has_key?(stop_meta, :error_type)

      # No exception event — errors are handled gracefully
      refute_received {^ref, @telemetry_prefix ++ [:exception], _, _}
    end

    test "does not emit telemetry when config validation fails" do
      result = OpenAI.complete([%{"role" => "user", "content" => "Hello"}], "gpt-4")

      assert {:error, _} = result

      refute_received {_, @telemetry_prefix ++ [:start], _, _}
      refute_received {_, @telemetry_prefix ++ [:stop], _, _}
    end
  end
end
