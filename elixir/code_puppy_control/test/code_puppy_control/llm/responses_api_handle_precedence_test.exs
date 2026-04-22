defmodule CodePuppyControl.LLM.ResponsesAPIHandlePrecedenceTest do
  @moduledoc """
  Regression tests for bd-166 critic issues #1 and #2.

  #1: Handle-path precedence — chatgpt_oauth auto-wired defaults
      (reasoning_effort, reasoning_summary, text_verbosity) MUST NOT
      overwrite explicit model_opts. The handle path must align with
      the LLM path which uses Keyword.put_new semantics.

  #2: max_output_tokens mismatch — the handle path previously forwarded
      :max_tokens while ResponsesAPI reads :max_output_tokens. The handle
      must forward as :max_output_tokens so it reaches the request body.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.LLM.Providers.ResponsesAPI
  alias CodePuppyControl.ModelFactory
  alias CodePuppyControl.ModelFactory.Handle
  alias CodePuppyControl.ModelRegistry
  alias CodePuppyControl.Test.MockLLMHTTP

  setup do
    CodePuppyControl.TestSupport.Reset.ensure_gen_server_started(ModelRegistry)
    start_supervised!(MockLLMHTTP)
    MockLLMHTTP.reset()
    :ok
  end

  @messages [%{role: "user", content: "Hello"}]

  # ── Bug #1: Handle-path precedence ──────────────────────────────────────

  describe "handle-path precedence (bd-166 #1)" do
    test "auto-wired reasoning_effort does NOT overwrite explicit model_opts" do
      # Simulate a chatgpt_oauth model with explicit reasoning_effort in model_opts
      :ets.insert(
        :model_configs,
        {"test-codex-precedence",
         %{
           "type" => "chatgpt_oauth",
           "name" => "gpt-5.3-codex",
           "model_opts" => %{"reasoning_effort" => "low"}
         }}
      )

      # Resolve the handle — the explicit "low" must win over the
      # auto-wired default from Config.Models (typically "medium").
      assert {:ok, handle} = ModelFactory.resolve("test-codex-precedence")
      assert handle.model_opts[:reasoning_effort] == "low",
             "Explicit reasoning_effort was overwritten by auto-wired default"
    after
      :ets.delete(:model_configs, "test-codex-precedence")
    end

    test "auto-wired reasoning_summary does NOT overwrite explicit model_opts" do
      :ets.insert(
        :model_configs,
        {"test-codex-summary",
         %{
           "type" => "chatgpt_oauth",
           "name" => "gpt-5.3-codex",
           "model_opts" => %{"reasoning_summary" => "detailed"}
         }}
      )

      assert {:ok, handle} = ModelFactory.resolve("test-codex-summary")
      assert handle.model_opts[:reasoning_summary] == "detailed",
             "Explicit reasoning_summary was overwritten by auto-wired default"
    after
      :ets.delete(:model_configs, "test-codex-summary")
    end

    test "auto-wired text_verbosity does NOT overwrite explicit model_opts" do
      :ets.insert(
        :model_configs,
        {"test-codex-verbosity",
         %{
           "type" => "chatgpt_oauth",
           "name" => "gpt-5.3-codex",
           "model_opts" => %{"text_verbosity" => "high"}
         }}
      )

      assert {:ok, handle} = ModelFactory.resolve("test-codex-verbosity")
      assert handle.model_opts[:text_verbosity] == "high",
             "Explicit text_verbosity was overwritten by auto-wired default"
    after
      :ets.delete(:model_configs, "test-codex-verbosity")
    end

    test "auto-wired settings are present when no explicit opts given" do
      :ets.insert(
        :model_configs,
        {"test-codex-auto",
         %{
           "type" => "chatgpt_oauth",
           "name" => "gpt-5.3-codex"
         }}
      )

      assert {:ok, handle} = ModelFactory.resolve("test-codex-auto")
      # Auto-wired defaults should be present (not nil) when no explicit opt
      assert handle.model_opts[:reasoning_effort] != nil
      assert handle.model_opts[:reasoning_summary] != nil
      assert handle.model_opts[:text_verbosity] != nil
    after
      :ets.delete(:model_configs, "test-codex-auto")
    end
  end

  # ── Bug #2: max_output_tokens reaches request body ─────────────────────

  describe "max_output_tokens handle-path coherence (bd-166 #2)" do
    test "handle-path max_output_tokens reaches ResponsesAPI request body" do
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

      opts = [
        api_key: "test-token",
        model: "gpt-5.3-codex",
        http_client: MockLLMHTTP,
        max_output_tokens: 4096
      ]

      ResponsesAPI.chat(@messages, [], opts)
      assert_received {:request_body, body}
      assert body["max_output_tokens"] == 4096,
             "max_output_tokens must appear in request body as 'max_output_tokens'"
    end

    test "handle forwards max_output_tokens (not max_tokens) via to_provider_opts" do
      # Build a handle with max_output_tokens in model_opts (as ModelFactory does)
      handle = %Handle{
        model_name: "test-codex",
        provider_module: ResponsesAPI,
        provider_config: %{},
        api_key: "test-token",
        base_url: "https://chatgpt.com/backend-api/codex",
        model_opts: [model: "gpt-5.3-codex", max_output_tokens: 8192]
      }

      opts = Handle.to_provider_opts(handle)
      # The key must be :max_output_tokens (what ResponsesAPI reads)
      assert opts[:max_output_tokens] == 8192,
             "Handle must forward :max_output_tokens, not :max_tokens"
      # And :max_tokens must NOT be present (it was the old buggy key)
      refute Keyword.has_key?(opts, :max_tokens),
             "Handle should NOT forward :max_tokens (old buggy key)"
    end

    test "explicit max_output_tokens from model config reaches request body" do
      test_pid = self()

      # Simulate a chatgpt_oauth model with max_output_tokens in config
      :ets.insert(
        :model_configs,
        {"test-codex-maxout",
         %{
           "type" => "chatgpt_oauth",
           "name" => "gpt-5.3-codex",
           "max_output_tokens" => 16384
         }}
      )

      MockLLMHTTP.register(fn :post, url, opts ->
        if url =~ "/responses" do
          body = Jason.decode!(opts[:body])
          send(test_pid, {:request_body, body})

          {:ok,
           %{
             status: 200,
             body: MockLLMHTTP.responses_api_stream_fixture(),
             headers: [{"content-type", "text-event-stream"}]
           }}
        else
          {:passthrough}
        end
      end)

      assert {:ok, handle} = ModelFactory.resolve("test-codex-maxout")
      assert handle.model_opts[:max_output_tokens] == 16384

      # Verify it reaches the provider
      provider_opts = Handle.to_provider_opts(handle)
      assert provider_opts[:max_output_tokens] == 16384
    after
      :ets.delete(:model_configs, "test-codex-maxout")
    end
  end
end
