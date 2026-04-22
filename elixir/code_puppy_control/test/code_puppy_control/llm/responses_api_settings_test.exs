defmodule CodePuppyControl.LLM.Providers.ResponsesAPISettingsTest do
  @moduledoc """
  Tests for ResponsesAPI settings forwarding and chatgpt_oauth routing.

  Covers: reasoning_effort, reasoning_summary, text_verbosity in request
  bodies, and provider routing for chatgpt_oauth model type.
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

  describe "request body: reasoning_summary and text_verbosity" do
    test "includes reasoning.summary in request body" do
      test_pid = self()
      opts = Keyword.put(@opts, :reasoning_summary, "concise")

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
      assert body["reasoning"]["summary"] == "concise"
    end

    test "includes both reasoning.effort and reasoning.summary" do
      test_pid = self()

      opts =
        @opts |> Keyword.put(:reasoning_effort, "high") |> Keyword.put(:reasoning_summary, "auto")

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
      assert body["reasoning"]["summary"] == "auto"
    end

    test "includes text.verbosity in request body" do
      test_pid = self()
      opts = Keyword.put(@opts, :text_verbosity, "low")

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
      assert body["text"]["verbosity"] == "low"
    end
  end

  describe "chatgpt_oauth routing to ResponsesAPI" do
    test "ModelFactory maps chatgpt_oauth type to ResponsesAPI provider" do
      {:ok, provider_mod} =
        CodePuppyControl.ModelFactory.provider_module_for_type("chatgpt_oauth")

      assert provider_mod == CodePuppyControl.LLM.Providers.ResponsesAPI
    end

    test "chatgpt_oauth does NOT route to the OpenAI ChatCompletions provider" do
      {:ok, provider_mod} =
        CodePuppyControl.ModelFactory.provider_module_for_type("chatgpt_oauth")

      # Verify chatgpt_oauth uses ResponsesAPI (not OpenAI Chat Completions)
      refute provider_mod == CodePuppyControl.LLM.Providers.OpenAI,
             "chatgpt_oauth must route to ResponsesAPI, not OpenAI ChatCompletions"
    end

    test "ResponsesAPI implements the Provider behaviour" do
      # Contract check: ResponsesAPI must export every Provider callback
      CodePuppyControl.Test.ProviderContract.validate_provider_interface(
        CodePuppyControl.LLM.Providers.ResponsesAPI,
        "ResponsesAPI"
      )
    end
  end
end
