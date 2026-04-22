defmodule CodePuppyControl.LLM.Providers.ResponsesAPITest do
  @moduledoc """
  Tests for the ResponsesAPI provider implementation.

  Uses MockLLMHTTP to return fixture responses without hitting real APIs.
  Covers: non-streaming chat, SSE streaming, tool calls, error handling,
  request body format (input instead of messages, store: false).
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

  describe "chat/3" do
    test "parses a successful Responses API response via forced stream=true" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(chunks: ["Hi there", "!"]),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      assert {:ok, response} = ResponsesAPI.chat(@messages, [], @opts)
      assert response.content == "Hi there!"
      assert response.finish_reason == "stop"
      assert response.tool_calls == []
      assert response.usage.prompt_tokens == 10
      assert response.usage.completion_tokens == 20
    end

    test "parses function_call from output via forced stream=true" do
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 200,
             body:
               MockLLMHTTP.responses_api_tool_stream_fixture(
                 tool_name: "get_weather",
                 call_id: "call_abc",
                 arguments: ~s({"location":"NYC"})
               ),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      assert {:ok, response} = ResponsesAPI.chat(@messages, [], @opts)
      assert response.content == nil
      assert length(response.tool_calls) == 1
      [tc] = response.tool_calls
      assert tc.id == "call_abc"
      assert tc.name == "get_weather"
      assert tc.arguments == %{"location" => "NYC"}
    end

    test "handles HTTP error status via streaming path" do
      # chat/3 forces stream=true; the mock returns a 401 status.
      # The stream handler checks HTTP status in {:done, metadata}.
      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          {:ok,
           %{
             status: 401,
             body: Jason.encode!(%{"error" => %{"message" => "Invalid token"}}),
             headers: []
           }}
        else
          {:passthrough}
        end
      end)

      assert {:error, %{status: 401}} = ResponsesAPI.chat(@messages, [], @opts)
    end

    test "sends correct request body with input and store: false" do
      test_pid = self()

      MockLLMHTTP.register(fn :post, url, opts ->
        if url =~ "/responses" do
          body = Jason.decode!(opts[:body])
          send(test_pid, {:request_body, body})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      ResponsesAPI.chat(@messages, [], @opts)
      assert_received {:request_body, body}
      assert body["model"] == "gpt-5.3-codex"
      assert body["stream"] == true
      assert body["store"] == false
      assert is_list(body["input"])
      assert length(body["input"]) == 1
      assert hd(body["input"])["role"] == "user"
      assert hd(body["input"])["content"] == "Hello"
      refute Map.has_key?(body, "messages")
    end

    test "includes reasoning effort in request body" do
      test_pid = self()
      opts = Keyword.put(@opts, :reasoning_effort, "high")

      MockLLMHTTP.register(fn :post, url, opts_r ->
        if url =~ "/responses" do
          body = Jason.decode!(opts_r[:body])
          send(test_pid, {:request_body, body})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      ResponsesAPI.chat(@messages, [], opts)
      assert_received {:request_body, body}
      assert body["reasoning"]["effort"] == "high"
    end

    test "includes tools in request body" do
      test_pid = self()

      tools = [
        %{
          type: "function",
          function: %{
            name: "get_weather",
            description: "Get the weather",
            parameters: %{
              "type" => "object",
              "properties" => %{"location" => %{"type" => "string"}}
            }
          }
        }
      ]

      MockLLMHTTP.register(fn :post, url, opts ->
        if url =~ "/responses" do
          body = Jason.decode!(opts[:body])
          send(test_pid, {:request_body, body})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      ResponsesAPI.chat(@messages, tools, @opts)
      assert_received {:request_body, body}
      assert is_list(body["tools"])
      assert length(body["tools"]) == 1
      assert hd(body["tools"])["name"] == "get_weather"
    end
  end

  describe "URL building" do
    test "appends /responses to base URL" do
      test_pid = self()

      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          send(test_pid, {:request_url, url})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      opts = Keyword.put(@opts, :base_url, "https://chatgpt.com/backend-api/codex")
      ResponsesAPI.chat(@messages, [], opts)
      assert_received {:request_url, url}
      assert url == "https://chatgpt.com/backend-api/codex/responses"
    end

    test "handles trailing slash in base URL" do
      test_pid = self()

      MockLLMHTTP.register(fn :post, url, _opts ->
        if url =~ "/responses" do
          send(test_pid, {:request_url, url})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      opts = Keyword.put(@opts, :base_url, "https://chatgpt.com/backend-api/codex/")
      ResponsesAPI.chat(@messages, [], opts)
      assert_received {:request_url, url}
      assert url == "https://chatgpt.com/backend-api/codex/responses"
      refute url =~ "//responses"
    end
  end

  describe "extra_headers forwarding" do
    test "OAuth headers are included in request" do
      test_pid = self()

      MockLLMHTTP.register(fn :post, url, opts ->
        if url =~ "/responses" do
          send(test_pid, {:request_headers, opts[:headers]})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      opts =
        @opts
        |> Keyword.put(:extra_headers, [
          {"ChatGPT-Account-Id", "acct_123"},
          {"originator", "codex_cli_rs"}
        ])

      ResponsesAPI.chat(@messages, [], opts)
      assert_received {:request_headers, headers}
      assert List.keyfind(headers, "authorization", 0) != nil
      assert List.keyfind(headers, "ChatGPT-Account-Id", 0) == {"ChatGPT-Account-Id", "acct_123"}
    end
  end

  describe "supports_tools?/0 and supports_vision?/0" do
    test "supports tools" do
      assert ResponsesAPI.supports_tools?() == true
    end

    test "supports vision" do
      assert ResponsesAPI.supports_vision?() == true
    end
  end

  describe "chat/3 forced stream=true parity" do
    test "chat/3 forces stream=true in request body (Codex backend requirement)" do
      test_pid = self()

      MockLLMHTTP.register(fn :post, url, opts ->
        if url =~ "/responses" do
          body = Jason.decode!(opts[:body])
          send(test_pid, {:request_body, body})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      assert {:ok, _response} = ResponsesAPI.chat(@messages, [], @opts)
      assert_received {:request_body, body}
      assert body["stream"] == true
    end

    test "chat/3 returns same response shape as stream_chat/4" do
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

      assert {:ok, response} = ResponsesAPI.chat(@messages, [], @opts)
      assert response.content == "Hello world!"
      assert response.finish_reason == "stop"
      assert response.tool_calls == []
      assert is_binary(response.id)
      assert is_binary(response.model)
    end

    test "chat/3 overrides stream: false to true (no native non-stream endpoint)" do
      # chat/3 forces stream=true and collects SSE back into a response.
      # This test verifies the request always goes out with stream=true,
      # proving there is no native non-stream code path.
      test_pid = self()

      # Explicitly pass stream: false to prove chat/3 overrides it
      opts_with_stream_false = Keyword.put(@opts, :stream, false)

      MockLLMHTTP.register(fn :post, url, opts ->
        if url =~ "/responses" do
          body = Jason.decode!(opts[:body])
          send(test_pid, {:request_body, body})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text/event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      assert {:ok, _response} = ResponsesAPI.chat(@messages, [], opts_with_stream_false)
      assert_received {:request_body, body}
      # Even though caller passed stream: false, chat/3 overrides to true
      assert body["stream"] == true,
             "chat/3 must force stream=true regardless of caller opts"
    end
  end

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
