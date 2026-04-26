defmodule CodePuppyControl.Agent.Loop do
  @moduledoc """
  GenServer that runs an agent's conversation loop.

  One `Loop` process per agent run. It drives the turn state machine:
  call LLM → stream → dispatch tools → repeat until done or max_turns.

  ## Lifecycle

      # Start a loop for an agent run
      {:ok, pid} = Loop.start_link(MyApp.Agents.ElixirDev, messages,
        run_id: "run-123",
        session_id: "session-456",
        max_turns: 25
      )

      # Run synchronously (blocks until done or error)
      :ok = Loop.run_until_done(pid, 30_000)

      # Or drive manually
      :ok = Loop.run_turn(pid)

  ## Events

  All events are published via `CodePuppyControl.EventBus` on the run topic.
  Subscribe with `EventBus.subscribe_run(run_id)` to receive them.

  ## Supervision

  Started under `CodePuppyControl.Run.Supervisor` (existing DynamicSupervisor).
  No separate supervisor needed — integrates with existing run infrastructure.

  ## LLM Integration

  The default `:llm_module` is `CodePuppyControl.Agent.LLMAdapter` which bridges the
  old `Agent.LLM` behaviour contract (atom tool names, `{:ok, response}` return) to the
  real `CodePuppyControl.LLM` provider contract (schema-map tools, `:ok` return with
  response delivered via `{:done, response}` callback). Tests may pass a mock via
  `opts[:llm_module]`.

  ## Compaction

  Before each LLM call, the loop checks whether the message history has
  grown beyond the compaction threshold. If so, it runs the three-phase
  compaction pipeline (filter, truncate, split) from `Compaction.compact/2`
  to reclaim tokens and keep the context window manageable.

  Compaction is **enabled by default** and configurable via start opts:

      # Disable compaction entirely
      Loop.start_link(agent, messages, compaction_enabled: false)

      # Customize compaction thresholds
      Loop.start_link(agent, messages,
        compaction_opts: [trigger_messages: 100, keep_fraction: 0.3]
      )

  When compaction runs, an `agent_messages_compacted` event is published
  via the EventBus with stats about what was reduced.
  """

  use GenServer

  require Logger

  alias CodePuppyControl.Agent.{Events, PromptMixin, ResponseValidator, Turn}
  alias CodePuppyControl.Compaction
  alias CodePuppyControl.Stream.{Event, Normalizer}
  alias CodePuppyControl.Tool.Runner
  alias CodePuppyControl.TokenLedger

  # ---------------------------------------------------------------------------
  # Client API
  # ---------------------------------------------------------------------------

  @typedoc "Options for starting an agent loop"
  @type start_opts :: [
          run_id: String.t(),
          session_id: String.t() | nil,
          max_turns: pos_integer(),
          llm_module: module(),
          metadata: map(),
          compaction_enabled: boolean(),
          compaction_opts: keyword(),
          model: String.t() | nil
        ]

  @doc """
  Starts an agent loop GenServer.

  ## Arguments

    * `agent_module` — Module implementing `Agent.Behaviour`
    * `initial_messages` — Starting message history (list of message maps)
    * `opts` — See `t:start_opts/0`

  ## Returns

    * `{:ok, pid}` — Loop started
    * `{:error, reason}` — Failed to start
  """
  @spec start_link(module(), [map()], start_opts()) :: GenServer.on_start()
  def start_link(agent_module, initial_messages, opts \\ []) do
    run_id = Keyword.get(opts, :run_id, generate_run_id())

    GenServer.start_link(__MODULE__, {agent_module, initial_messages, opts},
      name: via_tuple(run_id)
    )
  end

  @doc """
  Runs one turn of the agent loop.

  Calls the LLM, streams the response, dispatches any tool calls,
  and returns when the turn completes.

  Returns `:ok` if the turn completed, `{:error, reason}` otherwise.
  """
  @spec run_turn(GenServer.server()) :: :ok | {:error, term()}
  def run_turn(pid) do
    GenServer.call(pid, :run_turn, :infinity)
  end

  @doc """
  Runs the agent loop until completion or error.

  Executes turns in a loop, respecting `max_turns`. Returns `:ok` on
  successful completion, `{:error, reason}` on failure or turn limit.

  ## Options

    * `:timeout` — Per-turn timeout in ms (default: `:infinity`)
  """
  @spec run_until_done(GenServer.server(), non_neg_integer() | :infinity) ::
          :ok | {:error, term()}
  def run_until_done(pid, timeout \\ :infinity) do
    GenServer.call(pid, :run_until_done, timeout)
  end

  @doc """
  Gets the current loop state (for debugging/introspection).
  """
  @spec get_state(GenServer.server()) :: map()
  def get_state(pid) do
    GenServer.call(pid, :get_state)
  end

  @doc """
  Returns the current message history from the loop.

  Unlike `get_state/1`, this returns the raw message list so callers
  (e.g., the REPL) can write the final conversation back to `Agent.State`
  after `run_until_done/2` completes.
  """
  @spec get_messages(GenServer.server()) :: [map()]
  def get_messages(pid) do
    GenServer.call(pid, :get_messages)
  end

  @doc """
  Cancels the agent run.

  Sends a halt signal so the loop exits after the current operation.
  """
  @spec cancel(GenServer.server()) :: :ok
  def cancel(pid) do
    GenServer.cast(pid, :cancel)
  end

  @doc """
  Generates a unique run ID.

  Public so it can be used by `Agent.run/3` for generating IDs
  before starting the loop.
  """
  @spec generate_run_id() :: String.t()
  def generate_run_id do
    base = System.unique_integer([:positive])
    timestamp = System.system_time(:millisecond)
    "agent-#{timestamp}-#{base}"
  end

  # ---------------------------------------------------------------------------
  # Internal
  # ---------------------------------------------------------------------------

  defp via_tuple(run_id) do
    {:via, Registry, {CodePuppyControl.Run.Registry, {:agent_loop, run_id}}}
  end

  # ---------------------------------------------------------------------------
  # Server State
  # ---------------------------------------------------------------------------

  defstruct [
    :agent_module,
    :run_id,
    :session_id,
    :max_turns,
    :llm_module,
    :metadata,
    :messages,
    :turn,
    :turn_number,
    :agent_state,
    :cancelled,
    :completed,
    :model_override,
    compaction_enabled: true,
    compaction_opts: []
  ]

  @type server_state :: %__MODULE__{
          agent_module: module(),
          run_id: String.t(),
          session_id: String.t() | nil,
          max_turns: pos_integer(),
          llm_module: module(),
          metadata: map(),
          messages: [map()],
          turn: Turn.t() | nil,
          turn_number: non_neg_integer(),
          agent_state: map(),
          cancelled: boolean(),
          completed: boolean(),
          model_override: String.t() | nil,
          compaction_enabled: boolean(),
          compaction_opts: keyword()
        }

  # ---------------------------------------------------------------------------
  # Server Callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def init({agent_module, initial_messages, opts}) do
    run_id = Keyword.get(opts, :run_id, generate_run_id())
    session_id = Keyword.get(opts, :session_id)
    max_turns = Keyword.get(opts, :max_turns, 25)
    llm_module = Keyword.get(opts, :llm_module, CodePuppyControl.Agent.LLMAdapter)
    metadata = Keyword.get(opts, :metadata, %{})
    compaction_enabled = Keyword.get(opts, :compaction_enabled, true)
    compaction_opts = Keyword.get(opts, :compaction_opts, [])
    model_override = Keyword.get(opts, :model)

    state = %__MODULE__{
      agent_module: agent_module,
      run_id: run_id,
      session_id: session_id,
      max_turns: max_turns,
      llm_module: llm_module,
      metadata: metadata,
      messages: initial_messages,
      turn: nil,
      turn_number: 0,
      agent_state: %{turn_number: 0, tool_results: []},
      cancelled: false,
      completed: false,
      compaction_enabled: compaction_enabled,
      compaction_opts: compaction_opts,
      model_override: model_override
    }

    Logger.info(
      "Agent.Loop started: agent=#{inspect(agent_module)} run_id=#{run_id} " <>
        "session_id=#{session_id} max_turns=#{max_turns}"
    )

    {:ok, state}
  end

  @impl true
  def handle_call(:run_turn, _from, state) do
    case execute_turn(state) do
      {:ok, new_state} -> {:reply, :ok, new_state}
      {:error, reason, new_state} -> {:reply, {:error, reason}, new_state}
    end
  end

  @impl true
  def handle_call(:run_until_done, _from, state) do
    case run_loop(state) do
      {:ok, new_state} -> {:reply, :ok, %{new_state | completed: true}}
      {:error, reason, new_state} -> {:reply, {:error, reason}, new_state}
    end
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    view = %{
      run_id: state.run_id,
      session_id: state.session_id,
      agent_module: state.agent_module,
      turn_number: state.turn_number,
      max_turns: state.max_turns,
      message_count: length(state.messages),
      cancelled: state.cancelled,
      completed: state.completed,
      compaction_enabled: state.compaction_enabled,
      turn: if(state.turn, do: Turn.summary(state.turn), else: nil)
    }

    {:reply, view, state}
  end

  @impl true
  def handle_call(:get_messages, _from, state) do
    {:reply, state.messages, state}
  end

  @impl true
  def handle_cast(:cancel, state) do
    Logger.info("Agent.Loop cancelled: run_id=#{state.run_id}")
    {:noreply, %{state | cancelled: true}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("Agent.Loop received unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ---------------------------------------------------------------------------
  # Core Loop Logic
  # ---------------------------------------------------------------------------

  defp run_loop(%__MODULE__{cancelled: true} = state) do
    Logger.info("Agent.Loop stopped by cancellation: run_id=#{state.run_id}")

    Events.publish(
      Events.turn_ended(state.run_id, state.session_id, state.turn_number, :cancelled)
    )

    {:error, :cancelled, state}
  end

  defp run_loop(%__MODULE__{turn_number: n, max_turns: max} = state) when n >= max do
    Logger.info("Agent.Loop reached max_turns=#{max}: run_id=#{state.run_id}")

    Events.publish(
      Events.run_completed(state.run_id, state.session_id, %{reason: :max_turns_reached, turns: n})
    )

    {:ok, state}
  end

  defp run_loop(state) do
    case execute_turn(state) do
      {:ok, %{completed: true} = new_state} ->
        {:ok, new_state}

      {:ok, new_state} ->
        run_loop(new_state)

      {:error, reason, new_state} ->
        Events.publish(Events.run_failed(new_state.run_id, new_state.session_id, reason))
        {:error, reason, new_state}
    end
  end

  # ---------------------------------------------------------------------------
  # Turn Execution
  # ---------------------------------------------------------------------------

  defp execute_turn(state) do
    turn_number = state.turn_number + 1

    # Compact messages if needed before LLM call
    state = maybe_compact_messages(state)

    turn = Turn.new(turn_number, state.messages)

    with {:ok, turn} <- Turn.start_llm_call(turn),
         :ok <- Events.publish(Events.turn_started(state.run_id, state.session_id, turn_number)),
         {:ok, turn} <- do_llm_stream(state, turn) do
      handle_turn_result(state, turn, turn_number)
    else
      {:error, reason} ->
        {:error, reason, state}
    end
  end

  # ---------------------------------------------------------------------------
  # Compaction Integration
  # ---------------------------------------------------------------------------

  defp maybe_compact_messages(%{compaction_enabled: false} = state), do: state

  defp maybe_compact_messages(%{compaction_enabled: true} = state) do
    if Compaction.should_compact?(state.messages, state.compaction_opts) do
      compact_messages(state)
    else
      state
    end
  end

  defp compact_messages(state) do
    case Compaction.compact(state.messages, state.compaction_opts) do
      {:ok, compacted, stats} ->
        Logger.info(
          "Agent.Loop compaction: run_id=#{state.run_id} " <>
            "#{stats.original_count} -> #{length(compacted)} messages " <>
            "(dropped=#{stats.dropped_by_filter}, truncated=#{stats.truncated_count})"
        )

        Events.publish(
          Events.messages_compacted(state.run_id, state.session_id, %{
            original_count: stats.original_count,
            compacted_count: length(compacted),
            dropped_by_filter: stats.dropped_by_filter,
            truncated_count: stats.truncated_count,
            summarize_count: stats.summarize_count,
            protected_count: stats.protected_count
          })
        )

        %{state | messages: compacted}

      {:error, reason} ->
        Logger.warning(
          "Agent.Loop compaction failed: run_id=#{state.run_id} reason=#{inspect(reason)}"
        )

        # Fail gracefully — continue with original messages
        state
    end
  end

  defp do_llm_stream(state, turn) do
    case Turn.start_streaming(turn) do
      {:ok, turn} ->
        base_prompt =
          state.agent_module.system_prompt(%{
            session_id: state.session_id,
            run_id: state.run_id,
            messages: state.messages
          })

        identity = PromptMixin.get_identity(state.agent_module.name(), state.run_id)
        system_prompt = PromptMixin.get_full_system_prompt(base_prompt, identity)

        tools = state.agent_module.allowed_tools()
        model = resolve_model(state)

        raw_callback = build_stream_callback(state)
        stream_callback = Normalizer.normalize(raw_callback)

        case state.llm_module.stream_chat(
               state.messages,
               tools,
               [model: model, system_prompt: system_prompt],
               stream_callback
             ) do
          {:ok, response} ->
            turn = accumulate_response(turn, response)
            Turn.start_tool_calls(turn)

          {:error, reason} ->
            Turn.fail(turn, reason)
        end

      error ->
        error
    end
  end

  defp build_stream_callback(state) do
    fn
      {:stream, %Event.TextDelta{text: text}} when is_binary(text) ->
        Events.publish(Events.llm_stream(state.run_id, state.session_id, text))

      {:stream, %Event.ToolCallEnd{name: name, arguments: args_json, id: id}} ->
        arguments = parse_tool_arguments(args_json)

        Events.publish(
          Events.tool_call_start(state.run_id, state.session_id, name, arguments, id)
        )

      {:stream, %Event.Done{}} ->
        :ok

      {:stream, _other} ->
        :ok

      _other ->
        :ok
    end
  end

  defp parse_tool_arguments(args_json) when is_binary(args_json) do
    case Jason.decode(args_json) do
      {:ok, parsed} when is_map(parsed) -> parsed
      _ -> args_json
    end
  end

  defp parse_tool_arguments(args), do: args

  defp accumulate_response(turn, %{text: text, tool_calls: tool_calls}) do
    turn =
      if text && text != "" do
        case Turn.append_text(turn, text) do
          {:ok, t} -> t
          _ -> turn
        end
      else
        turn
      end

    Enum.reduce(tool_calls || [], turn, fn tc, acc ->
      case Turn.add_tool_call(acc, tc) do
        {:ok, t} -> t
        _ -> acc
      end
    end)
  end

  defp accumulate_response(turn, _other), do: turn

  defp handle_turn_result(state, %{state: :done} = turn, turn_number) do
    state = finalize_turn(state, turn, turn_number)
    Events.publish(Events.turn_ended(state.run_id, state.session_id, turn_number, :done))

    if Turn.has_pending_tools?(turn) == false and turn.accumulated_text != "" do
      # Text-only response, no tools — validate if schema defined, then complete
      case validate_response_if_schema(state, turn) do
        {:ok, _validated} ->
          Events.publish(
            Events.run_completed(state.run_id, state.session_id, %{
              turns: turn_number,
              reason: :text_response
            })
          )

          {:ok, %{state | completed: true}}

        {:error, validation_errors} ->
          {:error, {:validation_failed, validation_errors}, state}
      end
    else
      {:ok, state}
    end
  end

  # Validates response against agent's response_schema if defined.
  # Returns {:ok, response} if no schema or validation passes.
  # Returns {:error, errors} if validation fails.
  defp validate_response_if_schema(state, turn) do
    response = %{text: turn.accumulated_text, tool_calls: []}

    schema =
      if function_exported?(state.agent_module, :response_schema, 0) do
        state.agent_module.response_schema()
      else
        nil
      end

    ResponseValidator.validate(response, schema)
  end

  defp handle_turn_result(state, %{state: :error, error: reason} = turn, turn_number) do
    state = finalize_turn(state, turn, turn_number)
    Events.publish(Events.turn_ended(state.run_id, state.session_id, turn_number, :error))
    {:error, reason, state}
  end

  defp handle_turn_result(state, turn, turn_number) do
    state = finalize_turn(state, turn, turn_number)
    {:ok, state}
  end

  defp finalize_turn(state, turn, turn_number) do
    # Append accumulated text to messages as assistant response
    messages =
      if turn.accumulated_text != "" do
        state.messages ++ [%{role: "assistant", content: turn.accumulated_text}]
      else
        state.messages
      end

    # Dispatch tool calls and collect results
    messages = dispatch_tool_calls(state, turn, messages)

    # Record token usage in the ledger.
    # TODO: When real LLM usage data is available, replace these
    # zeros with actual prompt_tokens, completion_tokens, cached_tokens from
    # the provider response.
    model = resolve_model(state)

    status =
      case turn.state do
        :error -> :error
        _ -> :ok
      end

    TokenLedger.record_attempt(state.run_id, model,
      session_id: state.session_id,
      prompt_tokens: 0,
      completion_tokens: 0,
      cached_tokens: 0,
      status: status
    )

    %{
      state
      | turn: turn,
        turn_number: turn_number,
        messages: messages,
        agent_state: %{state.agent_state | turn_number: turn_number}
    }
  end

  # ---------------------------------------------------------------------------
  # Tool Dispatch — resolved via CodePuppyControl.Tool.Runner
  # ---------------------------------------------------------------------------

  defp dispatch_tool_calls(state, turn, messages) do
    allowed = MapSet.new(state.agent_module.allowed_tools())

    Enum.reduce(turn.pending_tool_calls, messages, fn tool_call, acc ->
      # Provider-emitted tool call names may arrive as strings, but
      # allowed_tools uses atoms. Resolve string names against the known
      # allowed set — never call String.to_atom/1 on untrusted input.
      resolved_name = resolve_tool_name(tool_call.name, allowed)
      tool_call = %{tool_call | name: resolved_name}

      if MapSet.member?(allowed, resolved_name) do
        execute_tool_call(state, tool_call, acc)
      else
        Logger.warning(
          "Agent.Loop: tool #{inspect(resolved_name)} not in allowed_tools for #{inspect(state.agent_module)}"
        )

        result_msg = %{
          role: "tool",
          tool_call_id: tool_call.id,
          content: "Error: tool #{inspect(resolved_name)} is not available"
        }

        Events.publish(
          Events.tool_call_end(
            state.run_id,
            state.session_id,
            resolved_name,
            {:error, :tool_not_allowed},
            tool_call.id
          )
        )

        acc ++ [result_msg]
      end
    end)
  end

  # Resolve a tool name (possibly a string from the provider) to an atom
  # by matching against the known allowed set. Returns the atom if found,
  # or the original name (string or atom) if no match — caller treats
  # unresolved strings as not-allowed.
  defp resolve_tool_name(name, _allowed) when is_atom(name), do: name

  defp resolve_tool_name(name, allowed) when is_binary(name) do
    case Enum.find(allowed, &(Atom.to_string(&1) == name)) do
      nil -> name
      atom -> atom
    end
  end

  defp resolve_tool_name(name, _allowed), do: name

  defp execute_tool_call(state, tool_call, messages) do
    Events.publish(
      Events.tool_call_start(
        state.run_id,
        state.session_id,
        tool_call.name,
        tool_call.arguments,
        tool_call.id
      )
    )

    # Dispatch via Tool.Runner (registry + permission check + validation + timeout)
    context = Runner.build_context(run_id: state.run_id)
    result = Runner.invoke(tool_call.name, tool_call.arguments, context)

    Events.publish(
      Events.tool_call_end(state.run_id, state.session_id, tool_call.name, result, tool_call.id)
    )

    # Check if agent wants to halt
    case state.agent_module.on_tool_result(tool_call.name, result, state.agent_state) do
      {:cont, _new_agent_state} ->
        result_msg = %{
          role: "tool",
          tool_call_id: tool_call.id,
          content: format_tool_result(result)
        }

        messages ++ [result_msg]

      {:halt, reason} ->
        Logger.info("Agent.Loop: agent halted after tool #{tool_call.name}: #{inspect(reason)}")

        messages
    end
  end

  defp format_tool_result({:ok, result}), do: inspect(result)
  defp format_tool_result({:error, reason}), do: "Error: #{inspect(reason)}"
  defp format_tool_result(other), do: inspect(other)

  # ---------------------------------------------------------------------------
  # Helpers
  # ---------------------------------------------------------------------------

  defp resolve_model(%__MODULE__{model_override: override})
       when is_binary(override) and override != "" do
    override
  end

  defp resolve_model(%__MODULE__{agent_module: agent_module}) do
    case agent_module.model_preference() do
      {:pack, role} ->
        # TODO: Integrate with model packs when available
        Logger.debug("Agent.Loop: model pack resolution not yet implemented for #{inspect(role)}")
        "claude-sonnet-4-20250514"

      model_name when is_binary(model_name) ->
        model_name
    end
  end
end
