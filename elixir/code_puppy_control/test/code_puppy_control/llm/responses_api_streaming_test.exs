defmodule CodePuppyControl.LLM.Providers.ResponsesAPIStreamingTest do
  @moduledoc """
  Streaming tests for the ResponsesAPI provider.

  Covers: stream_chat/4 event sequences, HTTP error handling,
  duplicate :part_end prevention, and exact event counts.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.LLM.Providers.ResponsesAPI
  alias CodePuppyControl.Test.MockLLMHTTP

  setup do
    start_supervised!(MockLLMHTTP)
    MockLLMHTTP.reset()
    :ok
  end

  @messages [%{role: "user", content: "Hello"}]
  @opts [api_key: "test-oauth-token", model: "gpt-5.3-codex", http_client: MockLLMHTTP]

  describe "stream_chat/4" do
    test "streams text content and emits events" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(chunks: ["Hello", " world", "!"]),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      events =
        capture_stream_events(fn callback ->
          :ok = ResponsesAPI.stream_chat(@messages, [], @opts, callback)
        end)

      starts = Enum.filter(events, &match?({:part_start, _}, &1))
      deltas = Enum.filter(events, &match?({:part_delta, _}, &1))
      ends = Enum.filter(events, &match?({:part_end, _}, &1))
      dones = Enum.filter(events, &match?({:done, _}, &1))

      # exactly 1 part_start for text
      assert length(starts) == 1
      assert length(deltas) == 3
      # exactly 1 part_end (no duplicates)
      assert length(ends) == 1
      assert length(dones) == 1

      delta_texts =
        deltas
        |> Enum.filter(fn {:part_delta, d} -> d.type == :text end)
        |> Enum.map(fn {:part_delta, d} -> d.text end)

      assert delta_texts == ["Hello", " world", "!"]

      [{:done, response}] = dones
      assert response.content == "Hello world!"
      assert response.finish_reason == "stop"
    end

    test "streams tool calls and emits events" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_tool_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      events =
        capture_stream_events(fn callback ->
          :ok = ResponsesAPI.stream_chat(@messages, [], @opts, callback)
        end)

      starts = Enum.filter(events, &match?({:part_start, %{type: :tool_call}}, &1))
      dones = Enum.filter(events, &match?({:done, _}, &1))

      assert length(starts) == 1
      assert length(dones) == 1

      [{:done, response}] = dones
      assert response.finish_reason == "stop"
      assert length(response.tool_calls) == 1
      [tc] = response.tool_calls
      assert tc.name == "get_weather"
      assert tc.arguments == %{"location" => "Boston"}
    end
  end

  describe "stream_chat/4 exact event counts (no duplicate :part_end)" do
    test "text streaming emits exactly 1 part_start, 3 deltas, 1 part_end, 1 done" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(chunks: ["A", "B", "C"]),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      events =
        capture_stream_events(fn callback ->
          :ok = ResponsesAPI.stream_chat(@messages, [], @opts, callback)
        end)

      starts = Enum.filter(events, &match?({:part_start, _}, &1))
      deltas = Enum.filter(events, &match?({:part_delta, _}, &1))
      ends = Enum.filter(events, &match?({:part_end, _}, &1))
      dones = Enum.filter(events, &match?({:done, _}, &1))

      assert length(starts) == 1
      assert length(deltas) == 3

      assert length(ends) == 1,
             "Expected exactly 1 part_end, got #{length(ends)} — duplicate :part_end bug"

      assert length(dones) == 1
    end

    test "tool call streaming emits exactly 1 part_start, 1 part_end, 1 done" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_tool_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      events =
        capture_stream_events(fn callback ->
          :ok = ResponsesAPI.stream_chat(@messages, [], @opts, callback)
        end)

      tc_starts = Enum.filter(events, &match?({:part_start, %{type: :tool_call}}, &1))

      tc_ends =
        Enum.filter(events, fn
          {:part_end, %{type: :tool_call}} -> true
          _ -> false
        end)

      dones = Enum.filter(events, &match?({:done, _}, &1))

      assert length(tc_starts) == 1

      assert length(tc_ends) == 1,
             "Expected exactly 1 tool_call part_end, got #{length(tc_ends)} — duplicate :part_end bug"

      assert length(dones) == 1
    end
  end

  describe "stream_chat/4 HTTP error handling" do
    test "returns error for non-2xx HTTP status" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 429,
             body: "rate limited",
             headers: []
           }}
        else
          {:passthrough}
        end
      end)

      assert {:error, %{status: 429}} =
               capture_stream_result(fn callback ->
                 ResponsesAPI.stream_chat(@messages, [], @opts, callback)
               end)
    end
  end

  describe "stream_chat/4 exact event sequence (duplicate :part_end prevention)" do
    test "text streaming event sequence is :part_start, :part_delta+, :part_end, :done" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(chunks: ["X", "Y"]),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      events =
        capture_stream_events(fn callback ->
          :ok = ResponsesAPI.stream_chat(@messages, [], @opts, callback)
        end)

      # Assert exact total event count: start + 2 deltas + end + done = 5
      assert length(events) == 5,
             "Expected 5 events, got #{length(events)}: #{inspect(Enum.map(events, fn {t, _} -> t end))}"

      # Assert exact event type sequence
      event_tags = Enum.map(events, fn {tag, _} -> tag end)

      assert event_tags == [:part_start, :part_delta, :part_delta, :part_end, :done],
             "Event sequence must be start->delta->delta->end->done, got: #{inspect(event_tags)}"

      # Confirm no second :part_end anywhere
      part_end_count = Enum.count(events, &match?({:part_end, _}, &1))

      assert part_end_count == 1,
             "Expected exactly 1 :part_end in sequence, got #{part_end_count}"
    end

    test "tool call streaming event sequence has exactly one :part_end" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_tool_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      events =
        capture_stream_events(fn callback ->
          :ok = ResponsesAPI.stream_chat(@messages, [], @opts, callback)
        end)

      part_end_count = Enum.count(events, &match?({:part_end, _}, &1))

      assert part_end_count == 1,
             "Expected exactly 1 :part_end for tool call, got #{part_end_count}"

      # Assert exact event type sequence for tool call stream
      event_tags = Enum.map(events, fn {tag, _} -> tag end)

      assert List.last(event_tags) == :done,
             "Last event must be :done, got: #{inspect(List.last(event_tags))}"

      assert List.last(Enum.drop(event_tags, -1)) == :part_end,
             "Second-to-last event must be :part_end, got: #{inspect(List.last(Enum.drop(event_tags, -1)))}"

      # No duplicate :part_end before :done
      pre_done_tags = Enum.drop(event_tags, -1)

      part_end_indices =
        pre_done_tags
        |> Enum.with_index()
        |> Enum.filter(fn {t, _} -> t == :part_end end)
        |> Enum.map(fn {_, i} -> i end)

      assert length(part_end_indices) == 1,
             "Expected exactly 1 :part_end before :done, found at indices: #{inspect(part_end_indices)}"
    end
  end

  # ── Helpers ───────────────────────────────────────────────────────────────
  defp capture_stream_result(callback_fn) do
    ref = make_ref()

    callback = fn
      {:done, _response} -> :ok
      _event -> :ok
    end

    result = callback_fn.(callback)
    send(self(), {:stream_result, result})
    result
  end

  defp capture_stream_events(callback_fn) do
    events = :ets.new(:stream_events, [:ordered_set, :public])

    callback = fn event ->
      idx = :ets.info(events, :size)
      :ets.insert(events, {idx, event})
    end

    callback_fn.(callback)

    result =
      :ets.tab2list(events)
      |> Enum.sort_by(fn {idx, _} -> idx end)
      |> Enum.map(fn {_, event} -> event end)

    :ets.delete(events)
    result
  end
end
