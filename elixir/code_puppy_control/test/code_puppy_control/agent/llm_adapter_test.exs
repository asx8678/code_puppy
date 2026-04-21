defmodule CodePuppyControl.Agent.LLMAdapterTest do
  @moduledoc """
  Direct unit tests for CodePuppyControl.Agent.LLMAdapter.

  Exercises the public stream_chat/4 interface with a mock LLM provider,
  verifying message conversion, tool resolution, response reconstruction,
  error handling, and adapter-owned timeout.
  """
  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.LLMAdapter
  alias CodePuppyControl.Tool.Registry

  # ---------------------------------------------------------------------------
  # Mock provider — CodePuppyControl.LLM contract (atom keys, schema-map
  # tools, raw events, returns :ok)
  # ---------------------------------------------------------------------------

  defmodule ProviderMock do
    @moduledoc "Configurable mock for the LLM provider layer."

    def start_if_needed do
      case Process.whereis(__MODULE__) do
        nil ->
          {:ok, _pid} = Elixir.Agent.start_link(fn -> %{} end, name: __MODULE__)

        _ ->
          :ok
      end
    end

    def set_response(response) do
      start_if_needed()
      Elixir.Agent.update(__MODULE__, &Map.put(&1, :response, response))
    end

    def set_silent_ok do
      # Provider returns :ok but never fires {:done, response} — exercises adapter timeout
      start_if_needed()
      Elixir.Agent.update(__MODULE__, &Map.put(&1, :silent_ok, true))
    end

    def set_error(reason) do
      start_if_needed()
      Elixir.Agent.update(__MODULE__, &Map.put(&1, :error, reason))
    end

    def captured_messages do
      start_if_needed()
      Elixir.Agent.get(__MODULE__, & &1)[:messages] || []
    end

    def captured_tools do
      start_if_needed()
      Elixir.Agent.get(__MODULE__, & &1)[:tools] || []
    end

    def reset do
      start_if_needed()
      Elixir.Agent.update(__MODULE__, fn _ -> %{} end)
    end

    def stop do
      try do
        Elixir.Agent.stop(__MODULE__)
      catch
        :exit, _ -> :ok
      end
    end

    # Provider contract: atom-keyed msgs, schema-map tools, raw events, :ok return
    @doc false
    def stream_chat(messages, tools, _opts, callback_fn) do
      start_if_needed()
      Elixir.Agent.update(__MODULE__, &Map.merge(&1, %{messages: messages, tools: tools}))

      state = Elixir.Agent.get(__MODULE__, & &1)

      cond do
        state[:error] ->
          {:error, state[:error]}

        state[:silent_ok] ->
          # Returns :ok without ever firing {:done, response} — exercises adapter timeout
          :ok

        state[:response] ->
          resp = state[:response]

          # Fire text streaming events if content present
          if resp[:content] do
            callback_fn.({:part_start, %{type: :text, index: 0, id: nil}})
            callback_fn.({:part_delta, %{type: :text, index: 0, text: resp.content, name: nil, arguments: nil}})
            callback_fn.({:part_end, %{type: :text, index: 0, id: nil}})
          end

          # Fire tool call events if present
          if resp[:tool_calls] do
            for tc <- resp[:tool_calls] do
              callback_fn.({:part_start, %{type: :tool_call, index: 1, id: tc[:id]}})
              callback_fn.({:part_delta, %{type: :tool_call, index: 1, text: nil, name: tc[:name], arguments: tc[:arguments]}})
              callback_fn.({:part_end, %{type: :tool_call, index: 1, id: tc[:id]}})
            end
          end

          # Fire terminal {:done, response} event — this is what LLMAdapter intercepts
          callback_fn.({:done, resp})
          :ok

        true ->
          # Default: minimal text response
          callback_fn.({:done, %{id: "r1", model: "test", content: "ok", tool_calls: [], finish_reason: "stop", usage: %{prompt_tokens: 0, completion_tokens: 0, total_tokens: 0}}})
          :ok
      end
    end
  end

  # ---------------------------------------------------------------------------
  # Stub tool for Registry-based tool resolution tests
  # ---------------------------------------------------------------------------


  defmodule StubTool do
    @moduledoc "Minimal tool module for Registry lookup tests."
    use CodePuppyControl.Tool

    @impl true
    def name, do: :stub_tool

    @impl true
    def description, do: "A stub tool for testing"

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "query" => %{"type" => "string", "description" => "A query string"}
        },
        "required" => ["query"]
      }
    end

    @impl true
    def invoke(_args, _context), do: {:ok, "stubbed"}
  end

  # ---------------------------------------------------------------------------
  # Setup / teardown
  # ---------------------------------------------------------------------------

  setup do
    # Swap in mock provider
    prev = Application.get_env(:code_puppy_control, :llm_adapter_provider)
    Application.put_env(:code_puppy_control, :llm_adapter_provider, ProviderMock)
    ProviderMock.reset()

    on_exit(fn ->
      if prev do
        Application.put_env(:code_puppy_control, :llm_adapter_provider, prev)
      else
        Application.delete_env(:code_puppy_control, :llm_adapter_provider)
      end

      ProviderMock.stop()
    end)

    :ok
  end

  # ===========================================================================
  # 1. Message conversion: parts-format → content-format
  # ===========================================================================

  describe "message conversion: parts-format → content-format" do
    test "flattens single text part into content field" do
      msgs = [%{"role" => "user", "parts" => [%{"type" => "text", "text" => "hello world"}]}]
      ProviderMock.set_response(%{id: "r1", content: "hi", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      captured = ProviderMock.captured_messages()
      assert length(captured) == 1
      assert [%{role: "user", content: "hello world"}] = captured
    end

    test "joins multiple text parts into single content string" do
      msgs = [
        %{
          "role" => "user",
          "parts" => [
            %{"type" => "text", "text" => "part one"},
            %{"type" => "text", "text" => "part two"}
          ]
        }
      ]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "part onepart two"}] = ProviderMock.captured_messages()
    end

    test "preserves tool_call_id from parts-format message" do
      msgs = [
        %{
          "role" => "tool",
          "parts" => [%{"type" => "text", "text" => "tool output"}],
          "tool_call_id" => "call_abc123"
        }
      ]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.role == "tool"
      assert captured.content == "tool output"
      assert captured.tool_call_id == "call_abc123"
    end

    test "handles mixed atom-keyed parts within string-keyed message" do
      # Agent.State may store parts with atom keys inside string-keyed envelope
      msgs = [
        %{
          "role" => "user",
          "parts" => [%{type: :text, text: "atom parts"}]
        }
      ]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "atom parts"}] = ProviderMock.captured_messages()
    end

    test "skips non-text part types gracefully" do
      msgs = [
        %{"role" => "user", "parts" => [
          %{"type" => "text", "text" => "visible"},
          %{"type" => "image", "url" => "http://example.com/img.png"}
        ]}
      ]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      # Non-text parts filtered out; only text is kept
      assert [%{role: "user", content: "visible"}] = ProviderMock.captured_messages()
    end
  end

  # ===========================================================================
  # 2. Message conversion: atom-keyed → string-keyed
  # ===========================================================================

  describe "message conversion: atom-keyed → string-keyed" do
    test "converts atom role to string role" do
      msgs = [%{role: :assistant, content: "I can help!"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "assistant", content: "I can help!"}] = ProviderMock.captured_messages()
    end

    test "converts :user atom role" do
      msgs = [%{role: :user, content: "Hello!"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "user", content: "Hello!"}] = ProviderMock.captured_messages()
    end

    test "preserves tool_call_id from atom-keyed message" do
      msgs = [%{role: :tool, content: "result", tool_call_id: "call_xyz"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.role == "tool"
      assert captured.tool_call_id == "call_xyz"
    end

    test "string-keyed content messages pass through with atom keys" do
      # Already string-keyed content format — should get atom-keyed output
      msgs = [%{"role" => "system", "content" => "You are helpful."}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      assert [%{role: "system", content: "You are helpful."}] = ProviderMock.captured_messages()
    end

    test "mixed key styles in tool_call_id extraction" do
      msgs = [%{role: :tool, content: "result", "tool_call_id" => "call_mixed"}]
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)

      [captured] = ProviderMock.captured_messages()
      assert captured.tool_call_id == "call_mixed"
    end
  end

  # ===========================================================================
  # 3. Tool conversion: atom names → JSON-Schema function maps via Tool.Registry
  # ===========================================================================

  describe "tool conversion: atom names → JSON-Schema function maps" do
    setup do
      # Use the app-supervised Registry; register stub and clean up in on_exit.
      :ok = Registry.register(StubTool)
      on_exit(fn -> Registry.unregister(:stub_tool) end)
      :ok
    end

    test "resolves registered tool atom to JSON-Schema function map" do
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat([%{"role" => "user", "content" => "hi"}], [:stub_tool], [model: "test"], fn _ -> :ok end)

      tools = ProviderMock.captured_tools()
      assert length(tools) == 1

      [tool] = tools
      assert tool[:type] == "function"
      assert tool[:function][:name] == "stub_tool"
      assert tool[:function][:description] == "A stub tool for testing"
      assert tool[:function][:parameters]["properties"]["query"]["type"] == "string"
    end

    test "skips unregistered tool names without crashing" do
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat([%{"role" => "user", "content" => "hi"}], [:stub_tool, :nonexistent_tool], [model: "test"], fn _ -> :ok end)

      tools = ProviderMock.captured_tools()
      # Only :stub_tool resolved; :nonexistent_tool silently skipped
      assert length(tools) == 1
      assert hd(tools)[:function][:name] == "stub_tool"
    end

    test "empty tool list produces empty schema list" do
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat([%{"role" => "user", "content" => "hi"}], [], [model: "test"], fn _ -> :ok end)

      assert ProviderMock.captured_tools() == []
    end

    test "multiple registered tools resolve in order" do
      # Register a second stub
      defmodule AnotherStubTool do
        use CodePuppyControl.Tool

        @impl true
        def name, do: :another_stub

        @impl true
        def description, do: "Another stub"

        @impl true
        def parameters, do: %{"type" => "object", "properties" => %{}}

        @impl true
        def invoke(_args, _context), do: {:ok, "another"}
      end

      :ok = Registry.register(AnotherStubTool)
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat([%{"role" => "user", "content" => "hi"}], [:stub_tool, :another_stub], [model: "test"], fn _ -> :ok end)

      tools = ProviderMock.captured_tools()
      assert length(tools) == 2
      names = Enum.map(tools, & &1[:function][:name])
      assert "stub_tool" in names
      assert "another_stub" in names
    after
      # Clean up the dynamically-registered tool from the app-supervised Registry
      Registry.unregister(:another_stub)
    end
  end

  # ===========================================================================
  # 4. Response reconstruction: :ok return with buffered text + tool_calls
  # ===========================================================================

  describe "response reconstruction: :ok return with buffered text + tool_calls" do
    test "returns {:ok, %{text, tool_calls}} for text-only response" do
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_response(%{id: "r1", content: "Hello, human!", tool_calls: []})

      assert {:ok, resp} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      assert resp.text == "Hello, human!"
      assert resp.tool_calls == []
    end

    test "extracts tool_calls from provider response" do
      msgs = [%{"role" => "user", "content" => "list files"}]
      tool_calls = [%{id: "tc1", name: "command_runner", arguments: %{"command" => "ls"}}]
      ProviderMock.set_response(%{id: "r1", content: "", tool_calls: tool_calls})

      assert {:ok, resp} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      assert resp.text == ""
      assert length(resp.tool_calls) == 1

      [tc] = resp.tool_calls
      assert tc.id == "tc1"
      assert tc.name == "command_runner"
      assert tc.arguments == %{"command" => "ls"}
    end

    test "handles multiple tool calls in response" do
      msgs = [%{"role" => "user", "content" => "multi-tool"}]
      tool_calls = [
        %{id: "tc1", name: "read_file", arguments: %{"path" => "a.ex"}},
        %{id: "tc2", name: "command_runner", arguments: %{"command" => "ls"}}
      ]
      ProviderMock.set_response(%{id: "r1", content: "", tool_calls: tool_calls})

      assert {:ok, resp} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      assert length(resp.tool_calls) == 2
      assert Enum.map(resp.tool_calls, & &1.name) == ["read_file", "command_runner"]
    end

    test "normalizes string-keyed tool calls to atom-keyed" do
      # Provider may return string-keyed tool calls
      msgs = [%{"role" => "user", "content" => "run"}]
      tool_calls = [%{"id" => "tc1", "name" => "read_file", "arguments" => %{"path" => "a.ex"}}]
      ProviderMock.set_response(%{id: "r1", content: "", tool_calls: tool_calls})

      assert {:ok, resp} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      assert length(resp.tool_calls) == 1

      [tc] = resp.tool_calls
      # Adapter normalizes to atom-keyed map
      assert tc.id == "tc1"
      assert tc.name == "read_file"
      assert tc.arguments == %{"path" => "a.ex"}
    end

    test "tool_call with nil id gets empty string default" do
      msgs = [%{"role" => "user", "content" => "run"}]
      tool_calls = [%{id: nil, name: "read_file", arguments: %{}}]
      ProviderMock.set_response(%{id: "r1", content: "", tool_calls: tool_calls})

      assert {:ok, resp} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      [tc] = resp.tool_calls
      assert tc.id == ""
    end

    test "response with both text and tool_calls" do
      msgs = [%{"role" => "user", "content" => "analyze"}]
      tool_calls = [%{id: "tc1", name: "read_file", arguments: %{"path" => "a.ex"}}]
      ProviderMock.set_response(%{id: "r1", content: "Let me check that file.", tool_calls: tool_calls})

      assert {:ok, resp} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      assert resp.text == "Let me check that file."
      assert length(resp.tool_calls) == 1
    end

    test "string-keyed content in response is extracted" do
      # Provider response may have string-keyed "content"
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_response(%{"id" => "r1", "content" => "string-keyed content", "tool_calls" => []})

      assert {:ok, resp} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      assert resp.text == "string-keyed content"
    end
  end

  # ===========================================================================
  # 5. Error pass-through: {:error, reason} propagates unchanged
  # ===========================================================================

  describe "error pass-through" do
    test "propagates {:error, reason} from provider unchanged" do
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_error(:rate_limited)

      assert {:error, :rate_limited} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
    end

    test "propagates string error reason" do
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_error("model overloaded")

      assert {:error, "model overloaded"} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
    end

    test "propagates tuple error reason" do
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_error({:http_error, 429})

      assert {:error, {:http_error, 429}} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
    end

    test "does not call callback on error" do
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_error(:timeout)

      callback_called = :atomics.new(1)

      assert {:error, :timeout} = LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ ->
        :atomics.add(callback_called, 1, 1)
      end)

      assert :atomics.get(callback_called, 1) == 0
    end
  end

  # ===========================================================================
  # 6. Tool registry missing: graceful [] fallback, no crash
  # ===========================================================================

  describe "tool registry missing: graceful fallback" do
    test "returns empty tool list when all tool names are unregistered" do
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(
        [%{"role" => "user", "content" => "hi"}],
        [:totally_fake_tool, :also_nonexistent],
        [model: "test"],
        fn _ -> :ok end
      )

      # No tools resolved — graceful [], not a crash
      assert ProviderMock.captured_tools() == []
    end

    test "non-atom tool names are skipped gracefully" do
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(
        [%{"role" => "user", "content" => "hi"}],
        ["string_tool_name", 123, nil],
        [model: "test"],
        fn _ -> :ok end
      )

      # Non-atom entries silently filtered
      assert ProviderMock.captured_tools() == []
    end

    test "resolve_tools rescue path returns [] for bad tool modules" do
      # Unregistered names return :error from Registry.lookup, which
      # resolve_single_tool handles as nil → filtered out. Verifies no crash.
      ProviderMock.set_response(%{id: "r1", content: "ok", tool_calls: []})

      assert {:ok, _} = LLMAdapter.stream_chat(
        [%{"role" => "user", "content" => "hi"}],
        [:no_such_tool_registered, :also_missing],
        [model: "test"],
        fn _ -> :ok end
      )

      assert ProviderMock.captured_tools() == []
    end
  end

  # ===========================================================================
  # 7. Adapter timeout: provider returns :ok but never emits {:done, response}
  # ===========================================================================

  describe "adapter timeout: provider silent :ok" do
    test "returns {:error, :adapter_timeout} when provider :ok without {:done, response}" do
      # Provider returns :ok but never fires {:done, response} → adapter's
      # receive block times out after 5s → {:error, :adapter_timeout}
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_silent_ok()

      task = Task.async(fn ->
        LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ -> :ok end)
      end)

      assert {:error, :adapter_timeout} = Task.await(task, 10_000)
    end

    test "adapter does not call upstream callback on silent :ok" do
      msgs = [%{"role" => "user", "content" => "hello"}]
      ProviderMock.set_silent_ok()

      callback_called = :atomics.new(1)

      task = Task.async(fn ->
        LLMAdapter.stream_chat(msgs, [], [model: "test"], fn _ ->
          :atomics.add(callback_called, 1, 1)
        end)
      end)

      assert {:error, :adapter_timeout} = Task.await(task, 10_000)
      # No events emitted → upstream callback never invoked
      assert :atomics.get(callback_called, 1) == 0
    end
  end
end
