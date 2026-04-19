defmodule CodePuppyControl.Agent.LoopTest do
  use ExUnit.Case, async: false

  alias CodePuppyControl.Agent.Loop

  # ---------------------------------------------------------------------------
  # Mock Agent Module
  # ---------------------------------------------------------------------------

  defmodule TestAgent do
    @behaviour CodePuppyControl.Agent.Behaviour

    @impl true
    def name, do: :test_agent

    @impl true
    def system_prompt(_ctx), do: "You are a test agent."

    @impl true
    def allowed_tools, do: [:echo_tool]

    @impl true
    def model_preference, do: "test-model"

    @impl true
    def on_tool_result(_tool, _result, state), do: {:cont, state}
  end

  # ---------------------------------------------------------------------------
  # Mock LLM Module
  # ---------------------------------------------------------------------------

  defmodule MockLLM do
    @behaviour CodePuppyControl.Agent.LLM

    def start_link do
      # Use start instead of start_link to avoid linking issues
      case Agent.start(fn -> %{} end, name: __MODULE__) do
        {:ok, pid} -> {:ok, pid}
        {:error, {:already_started, pid}} -> {:ok, pid}
      end
    end

    def set_response(response) do
      Agent.update(__MODULE__, fn _ -> %{response: response} end)
    end

    def stop do
      try do
        Agent.stop(__MODULE__)
      catch
        :exit, _ -> :ok
      end
    end

    @impl true
    def stream_chat(_messages, _tools, _opts, callback_fn) do
      response = Agent.get(__MODULE__, fn state -> state.response end)

      case response do
        %{text: text} when is_binary(text) ->
          callback_fn.({:text, text})

        %{text: text, tool_calls: tool_calls} when is_list(tool_calls) ->
          if text, do: callback_fn.({:text, text})

          for tc <- tool_calls do
            callback_fn.({:tool_call, tc.name, tc.arguments, tc.id})
          end

        _ ->
          :ok
      end

      callback_fn.({:done, :complete})
      {:ok, response}
    end
  end

  # ---------------------------------------------------------------------------
  # Mock Tool — defined here so it's compiled and loadable
  # ---------------------------------------------------------------------------

  defmodule Tool.EchoTool do
    def execute(%{"input" => input}), do: {:ok, "echo: #{input}"}
    def execute(_), do: {:ok, "echo"}
  end

  # ---------------------------------------------------------------------------
  # Setup
  # ---------------------------------------------------------------------------

  setup do
    # Start (or restart) mock LLM for each test
    {:ok, _pid} = MockLLM.start_link()
    on_exit(fn -> MockLLM.stop() end)
    :ok
  end

  # ---------------------------------------------------------------------------
  # Tests
  # ---------------------------------------------------------------------------

  describe "start_link/3" do
    test "starts a loop GenServer" do
      {:ok, pid} = Loop.start_link(TestAgent, [], llm_module: MockLLM, run_id: "test-start-1")
      assert Process.alive?(pid)

      state = Loop.get_state(pid)
      assert state.run_id == "test-start-1"
      assert state.agent_module == TestAgent
      assert state.turn_number == 0
      assert state.message_count == 0
      assert state.cancelled == false
      assert state.completed == false

      GenServer.stop(pid)
    end

    test "auto-generates run_id when not provided" do
      {:ok, pid} = Loop.start_link(TestAgent, [], llm_module: MockLLM)
      state = Loop.get_state(pid)
      assert String.starts_with?(state.run_id, "agent-")
      GenServer.stop(pid)
    end
  end

  describe "run_turn/1 — text-only response" do
    test "completes a single text turn" do
      MockLLM.set_response(%{text: "Hello!", tool_calls: []})

      {:ok, pid} = Loop.start_link(TestAgent, [], llm_module: MockLLM, run_id: "test-turn-1")
      assert :ok = Loop.run_turn(pid)

      state = Loop.get_state(pid)
      assert state.turn_number == 1

      GenServer.stop(pid)
    end

    test "accumulates messages after turn" do
      MockLLM.set_response(%{text: "Hi there", tool_calls: []})

      messages = [%{role: "user", content: "hello"}]

      {:ok, pid} =
        Loop.start_link(TestAgent, messages, llm_module: MockLLM, run_id: "test-turn-2")

      :ok = Loop.run_turn(pid)

      state = Loop.get_state(pid)
      # original + assistant response
      assert state.message_count == 2

      GenServer.stop(pid)
    end
  end

  describe "run_until_done/2" do
    test "completes text-only run in one turn" do
      MockLLM.set_response(%{text: "Done!", tool_calls: []})

      {:ok, pid} = Loop.start_link(TestAgent, [], llm_module: MockLLM, run_id: "test-done-1")

      assert :ok = Loop.run_until_done(pid, 5_000)

      state = Loop.get_state(pid)
      assert state.completed == true
      assert state.turn_number == 1

      GenServer.stop(pid)
    end

    test "respects max_turns limit" do
      # Always return a tool call so we keep going
      MockLLM.set_response(%{
        text: nil,
        tool_calls: [%{id: "tc-1", name: :echo_tool, arguments: %{"input" => "hi"}}]
      })

      {:ok, pid} =
        Loop.start_link(TestAgent, [],
          llm_module: MockLLM,
          run_id: "test-max-turns",
          max_turns: 3
        )

      assert :ok = Loop.run_until_done(pid, 10_000)

      state = Loop.get_state(pid)
      assert state.turn_number == 3

      GenServer.stop(pid)
    end
  end

  describe "cancel/1" do
    test "cancellation stops the loop" do
      # Use a response with tool calls so the loop would continue
      MockLLM.set_response(%{
        text: nil,
        tool_calls: [%{id: "tc-1", name: :echo_tool, arguments: %{"input" => "hi"}}]
      })

      {:ok, pid} =
        Loop.start_link(TestAgent, [],
          llm_module: MockLLM,
          run_id: "test-cancel",
          max_turns: 100
        )

      # Cancel immediately, then try to run
      Loop.cancel(pid)

      # Give the cast a moment to process
      Process.sleep(50)

      result = Loop.run_until_done(pid, 5_000)
      assert {:error, :cancelled} = result

      GenServer.stop(pid)
    end
  end

  describe "event emission" do
    test "emits turn_started and turn_ended events" do
      run_id = "test-events-1"

      # Subscribe BEFORE starting the loop
      Phoenix.PubSub.subscribe(CodePuppyControl.PubSub, "run:#{run_id}")

      # Small delay to ensure subscription propagates
      Process.sleep(10)

      MockLLM.set_response(%{text: "Hello", tool_calls: []})

      {:ok, pid} =
        Loop.start_link(TestAgent, [],
          llm_module: MockLLM,
          run_id: run_id
        )

      :ok = Loop.run_turn(pid)

      # Collect events with reasonable timeout
      events = collect_events(500)

      # Events have atom keys, not string keys!
      turn_started = Enum.find(events, fn e -> e[:type] == "agent_turn_started" end)
      turn_ended = Enum.find(events, fn e -> e[:type] == "agent_turn_ended" end)

      assert turn_started != nil,
             "Expected agent_turn_started event, got: #{inspect(Enum.map(events, & &1[:type]))}"

      assert turn_started[:turn_number] == 1

      assert turn_ended != nil, "Expected agent_turn_ended event"
      assert turn_ended[:turn_number] == 1

      GenServer.stop(pid)
    end

    test "emits llm_stream events" do
      run_id = "test-events-2"

      # Subscribe BEFORE starting the loop
      Phoenix.PubSub.subscribe(CodePuppyControl.PubSub, "run:#{run_id}")

      # Small delay to ensure subscription propagates
      Process.sleep(10)

      MockLLM.set_response(%{text: "streaming text", tool_calls: []})

      {:ok, pid} =
        Loop.start_link(TestAgent, [],
          llm_module: MockLLM,
          run_id: run_id
        )

      :ok = Loop.run_turn(pid)

      # Collect events with reasonable timeout
      events = collect_events(500)

      # Events have atom keys, not string keys!
      stream_events = Enum.filter(events, fn e -> e[:type] == "agent_llm_stream" end)

      assert length(stream_events) >= 1,
             "Expected at least one agent_llm_stream event, got: #{inspect(Enum.map(events, & &1[:type]))}"

      GenServer.stop(pid)
    end
  end

  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  defp collect_events(timeout) do
    collect_events([], timeout)
  end

  defp collect_events(acc, timeout) do
    receive do
      {:event, event} -> collect_events([event | acc], timeout)
    after
      timeout -> Enum.reverse(acc)
    end
  end
end
