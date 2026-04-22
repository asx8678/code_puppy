defmodule CodePuppyControl.LLM.ResponsesAPICollectorSSETest do
  @moduledoc """
  Regression tests for bd-166 critic issues #3 and #4.

  #3: Collector completion / cleanup hardening.
  #4: SSE done-event parity + out-of-order preservation.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.LLM.Providers.ResponsesAPI
  alias CodePuppyControl.LLM.Providers.ResponsesAPI.SSE
  alias CodePuppyControl.Test.MockLLMHTTP

  setup do
    start_supervised!(MockLLMHTTP)
    MockLLMHTTP.reset()
    :ok
  end

  @messages [%{role: "user", content: "Hello"}]
  @opts [api_key: "test-oauth-token", model: "gpt-5.3-codex", http_client: MockLLMHTTP]

  describe "collector cleanup (bd-166 #3)" do
    test "chat/3 does not leak collector messages on error" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok, %{status: 401, body: Jason.encode!(%{"error" => %{"message" => "Invalid token"}}), headers: []}}
        else
          {:passthrough}
        end
      end)

      assert {:error, _} = ResponsesAPI.chat(@messages, [], @opts)
      refute_received {:collected_response, _}
    end

    test "chat/3 returns error when stream returns error" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:error, :connection_refused}
        else
          {:passthrough}
        end
      end)

      assert {:error, _} = ResponsesAPI.chat(@messages, [], @opts)
    end
  end

  describe "SSE done-event parity (bd-166 #4)" do
    test "output_text.done backfills when no deltas arrived" do
      nl = "
"
      nn = "

"
      sse_body =
        "event: response.created" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.created", "response" => %{"id" => "r1", "model" => "gpt-5.3-codex", "status" => "in_progress", "output" => [], "usage" => %{}}}) <> nn <>
        "event: response.output_item.added" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_item.added", "output_index" => 0, "item" => %{"type" => "message", "id" => "m1", "role" => "assistant", "content" => []}}) <> nn <>
        "event: response.output_text.done" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_text.done", "output_index" => 0, "content_index" => 0, "text" => "Done-only"}) <> nn <>
        "event: response.output_item.done" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_item.done", "output_index" => 0, "item" => %{"type" => "message", "id" => "m1", "role" => "assistant", "content" => [%{"type" => "output_text", "text" => "Done-only"}]}}) <> nn <>
        "event: response.completed" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.completed", "response" => %{"id" => "r1", "object" => "response", "model" => "gpt-5.3-codex", "status" => "completed", "output" => [%{"type" => "message", "id" => "m1", "role" => "assistant", "content" => [%{"type" => "output_text", "text" => "Done-only"}]}], "usage" => %{"input_tokens" => 5, "output_tokens" => 3, "total_tokens" => 8}}}) <> nn

      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses", do: {:ok, %{status: 200, body: sse_body, headers: [{"content-type", "text/event-stream"}]}}, else: {:passthrough}
      end)

      assert {:ok, response} = ResponsesAPI.chat(@messages, [], @opts)
      assert response.content == "Done-only", "output_text.done must backfill when no deltas"
    end

    test "function_call_arguments.done backfills when no deltas" do
      nl = "
"
      nn = "

"
      fa = ~s({"location":"NYC"})
      sse_body =
        "event: response.created" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.created", "response" => %{"id" => "r2", "model" => "gpt-5.3-codex", "status" => "in_progress", "output" => [], "usage" => %{}}}) <> nn <>
        "event: response.output_item.added" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_item.added", "output_index" => 0, "item" => %{"type" => "function_call", "id" => "fc1", "call_id" => "c1", "name" => "get_weather", "arguments" => ""}}) <> nn <>
        "event: response.function_call_arguments.done" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.function_call_arguments.done", "output_index" => 0, "arguments" => fa}) <> nn <>
        "event: response.output_item.done" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_item.done", "output_index" => 0, "item" => %{"type" => "function_call", "id" => "fc1", "call_id" => "c1", "name" => "get_weather", "arguments" => fa}}) <> nn <>
        "event: response.completed" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.completed", "response" => %{"id" => "r2", "object" => "response", "model" => "gpt-5.3-codex", "status" => "completed", "output" => [%{"type" => "function_call", "id" => "fc1", "call_id" => "c1", "name" => "get_weather", "arguments" => fa}], "usage" => %{"input_tokens" => 5, "output_tokens" => 10, "total_tokens" => 15}}}) <> nn

      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses", do: {:ok, %{status: 200, body: sse_body, headers: [{"content-type", "text/event-stream"}]}}, else: {:passthrough}
      end)

      assert {:ok, response} = ResponsesAPI.chat(@messages, [], @opts)
      assert length(response.tool_calls) == 1
      tc = hd(response.tool_calls)
      assert tc.name == "get_weather"
      assert tc.arguments == %{"location" => "NYC"}, "function_call_arguments.done must backfill"
    end

    test "output_item.added does NOT wipe out-of-order deltas" do
      nl = "
"
      nn = "

"
      sse_body =
        "event: response.created" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.created", "response" => %{"id" => "r3", "model" => "gpt-5.3-codex", "status" => "in_progress", "output" => [], "usage" => %{}}}) <> nn <>
        "event: response.output_text.delta" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_text.delta", "output_index" => 0, "content_index" => 0, "delta" => "Early "}) <> nn <>
        "event: response.output_text.delta" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_text.delta", "output_index" => 0, "content_index" => 0, "delta" => "bird"}) <> nn <>
        "event: response.output_item.added" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_item.added", "output_index" => 0, "item" => %{"type" => "message", "id" => "m3", "role" => "assistant", "content" => []}}) <> nn <>
        "event: response.output_text.done" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_text.done", "output_index" => 0, "content_index" => 0, "text" => "Early bird"}) <> nn <>
        "event: response.output_item.done" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.output_item.done", "output_index" => 0, "item" => %{"type" => "message", "id" => "m3", "role" => "assistant", "content" => [%{"type" => "output_text", "text" => "Early bird"}]}}) <> nn <>
        "event: response.completed" <> nl <>
        "data: " <> Jason.encode!(%{"type" => "response.completed", "response" => %{"id" => "r3", "object" => "response", "model" => "gpt-5.3-codex", "status" => "completed", "output" => [%{"type" => "message", "id" => "m3", "role" => "assistant", "content" => [%{"type" => "output_text", "text" => "Early bird"}]}], "usage" => %{"input_tokens" => 5, "output_tokens" => 2, "total_tokens" => 7}}}) <> nn

      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses", do: {:ok, %{status: 200, body: sse_body, headers: [{"content-type", "text/event-stream"}]}}, else: {:passthrough}
      end)

      assert {:ok, response} = ResponsesAPI.chat(@messages, [], @opts)
      assert response.content == "Early bird", "Out-of-order deltas must be preserved"
    end

    test "fragmented SSE chunk exercises parser buffering" do
      base_body = MockLLMHTTP.responses_api_stream_fixture(chunks: ["Hello", " world"])
      case :binary.match(base_body, "response.output_text.delta") do
        {pos, _len} ->
          sp = pos + 24
          <<first::binary-size(sp), rest::binary>> = base_body
          MockLLMHTTP.register(fn :post, url, _opts ->
            if url =~ "/responses", do: {:ok, %{status: 200, body: first <> rest, headers: [{"content-type", "text/event-stream"}]}}, else: {:passthrough}
          end)
          assert {:ok, response} = ResponsesAPI.chat(@messages, [], @opts)
          assert response.content == "Hello world"
        :nomatch ->
          flunk("Could not find delta event in SSE fixture")
      end
    end
  end

  describe "SSE module unit tests (bd-166 #4)" do
    test "output_text.done backfills empty content part" do
      acc = %{line_buf: "", current_event: nil, current_data: "", id: nil, model: nil,
        content_parts: %{0 => %{type: :text, index: 0, text_chunks: []}},
        tool_calls: %{}, ended_parts: MapSet.new(), http_status: nil, usage: nil, status: nil}
      data = %{"output_index" => 0, "text" => "Backfilled!"}
      callback = fn _event -> :ok end
      assert {:ok, new_acc} = SSE.handle_sse_event("response.output_text.done", data, acc, callback)
      assert new_acc.content_parts[0].text_chunks == ["Backfilled!"]
    end

    test "output_text.done preserves existing chunks" do
      acc = %{line_buf: "", current_event: nil, current_data: "", id: nil, model: nil,
        content_parts: %{0 => %{type: :text, index: 0, text_chunks: ["Hello ", "world"]}},
        tool_calls: %{}, ended_parts: MapSet.new(), http_status: nil, usage: nil, status: nil}
      data = %{"output_index" => 0, "text" => "Hello world"}
      callback = fn _event -> :ok end
      assert {:ok, new_acc} = SSE.handle_sse_event("response.output_text.done", data, acc, callback)
      assert new_acc.content_parts[0].text_chunks == ["Hello ", "world"]
    end

    test "function_call_arguments.done backfills empty arg_chunks" do
      acc = %{line_buf: "", current_event: nil, current_data: "", id: nil, model: nil,
        content_parts: %{},
        tool_calls: %{0 => %{type: :tool_call, index: 0, id: "c1", name: "gw", arg_chunks: []}},
        ended_parts: MapSet.new(), http_status: nil, usage: nil, status: nil}
      data = %{"output_index" => 0, "arguments" => ~s({"location":"NYC"})}
      callback = fn _event -> :ok end
      assert {:ok, new_acc} = SSE.handle_sse_event("response.function_call_arguments.done", data, acc, callback)
      assert new_acc.tool_calls[0].arg_chunks == [~s({"location":"NYC"})]
    end

    test "function_call_arguments.done preserves existing arg_chunks" do
      acc = %{line_buf: "", current_event: nil, current_data: "", id: nil, model: nil,
        content_parts: %{},
        tool_calls: %{0 => %{type: :tool_call, index: 0, id: "c1", name: "gw", arg_chunks: ["{\"loc", "ation\":\"NYC\"}"]}},
        ended_parts: MapSet.new(), http_status: nil, usage: nil, status: nil}
      data = %{"output_index" => 0, "arguments" => ~s({"location":"NYC"})}
      callback = fn _event -> :ok end
      assert {:ok, new_acc} = SSE.handle_sse_event("response.function_call_arguments.done", data, acc, callback)
      assert new_acc.tool_calls[0].arg_chunks == ["{\"loc", "ation\":\"NYC\"}"]
    end

    test "output_item.added preserves pre-existing content chunks" do
      acc = %{line_buf: "", current_event: nil, current_data: "", id: nil, model: nil,
        content_parts: %{0 => %{type: :text, index: 0, text_chunks: ["Pre-", "existing"]}},
        tool_calls: %{}, ended_parts: MapSet.new(), http_status: nil, usage: nil, status: nil}
      data = %{"output_index" => 0, "item" => %{"type" => "message", "id" => "ml", "role" => "assistant", "content" => []}}
      callback = fn _event -> :ok end
      assert {:ok, new_acc} = SSE.handle_sse_event("response.output_item.added", data, acc, callback)
      assert new_acc.content_parts[0].text_chunks == ["Pre-", "existing"],
        "output_item.added must NOT wipe earlier out-of-order delta chunks"
    end

    test "output_item.added preserves pre-existing tool call arg_chunks" do
      acc = %{line_buf: "", current_event: nil, current_data: "", id: nil, model: nil,
        content_parts: %{},
        tool_calls: %{0 => %{type: :tool_call, index: 0, id: "ce", name: "rc", arg_chunks: ["{\"cm", "d\":\"ls\"}"]}},
        ended_parts: MapSet.new(), http_status: nil, usage: nil, status: nil}
      data = %{"output_index" => 0, "item" => %{"type" => "function_call", "id" => "fl", "call_id" => "cl", "name" => "rc", "arguments" => ""}}
      callback = fn _event -> :ok end
      assert {:ok, new_acc} = SSE.handle_sse_event("response.output_item.added", data, acc, callback)
      assert new_acc.tool_calls[0].arg_chunks == ["{\"cm", "d\":\"ls\"}"],
        "output_item.added must NOT wipe earlier out-of-order arg chunks"
    end
  end
end
