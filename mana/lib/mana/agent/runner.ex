defmodule Mana.Agent.Runner do
  @moduledoc """
  Core agent execution loop — replaces pydantic-ai Agent.run()

  This module provides the main execution loop for running agents synchronously
  and with streaming. It handles:

  - System prompt assembly via Prompt.Compositor
  - Message history management
  - Tool call dispatch and execution
  - History compaction
  - Session persistence
  - Callback dispatch at key lifecycle points

  ## Usage

  Synchronous run:

      {:ok, pid} = Mana.Agent.Server.start_link(agent_def: agent_def)
      {:ok, response} = Mana.Agent.Runner.run(pid, "Hello, how are you?")

  Streaming run:

      stream = Mana.Agent.Runner.stream(pid, "Hello, how are you?")
      Enum.each(stream, fn event -> handle_event(event) end)

  """

  alias Mana.Agent.Compaction
  alias Mana.Agent.Server
  alias Mana.Callbacks
  alias Mana.Models.Settings
  alias Mana.Prompt.Compositor
  alias Mana.Session.Store
  alias Mana.Tools.Registry, as: ToolsRegistry

  @telemetry_prefix [:mana, :agent, :run]

  @doc """
  Run agent synchronously — returns final response.

  ## Parameters

  - `agent_server` - PID of the agent server or a map with agent_state
  - `user_message` - The user message to send to the agent
  - `opts` - Keyword list of options:
    - `:max_iterations` - Maximum tool call iterations (default: 10)
    - `:async` - Whether to run asynchronously (default: false)

  ## Returns

  - `{:ok, String.t()}` - The final response text
  - `{:error, term()}` - An error occurred

  ## Examples

      {:ok, pid} = Mana.Agent.Server.start_link(agent_def: agent_def)
      {:ok, response} = Mana.Agent.Runner.run(pid, "What is Elixir?")

  """
  @spec run(pid() | map(), String.t(), keyword()) :: {:ok, String.t()} | {:error, term()}
  def run(agent_server, user_message, opts \\ [])

  def run(agent_pid, user_message, opts) when is_pid(agent_pid) do
    agent_state = Server.get_state(agent_pid)
    run(agent_state, user_message, opts)
  end

  def run(agent_state, user_message, opts) when is_map(agent_state) do
    timeout = Keyword.get(opts, :timeout, 120_000)

    task =
      Task.Supervisor.async_nolink(Mana.TaskSupervisor, fn ->
        do_run_with_state(agent_state, user_message, opts)
      end)

    case Task.yield(task, timeout) || Task.shutdown(task) do
      {:ok, result} ->
        result

      nil ->
        # Fire :agent_run_end callback for timeout
        agent_def = agent_state.agent_def
        model_name = agent_state.model_name
        session_id = agent_state.session_id || generate_session_id()
        agent_name = agent_def[:name] || "agent"

        Callbacks.dispatch(:agent_run_end, [
          agent_name,
          model_name,
          session_id,
          false,
          :timeout,
          nil,
          %{}
        ])

        {:error, :timeout}
    end
  end

  defp do_run_with_state(agent_state, user_message, opts) do
    agent_def = agent_state.agent_def
    model_name = agent_state.model_name
    session_id = agent_state.session_id || generate_session_id()
    agent_name = agent_def[:name] || "agent"

    start_meta = %{agent_name: agent_name, model: model_name, session_id: session_id}

    :telemetry.span(
      @telemetry_prefix,
      start_meta,
      fn ->
        do_run_with_state_inner(
          agent_state,
          user_message,
          opts,
          agent_def,
          model_name,
          session_id,
          agent_name
        )
      end
    )
  end

  defp do_run_with_state_inner(
         agent_state,
         user_message,
         opts,
         agent_def,
         model_name,
         session_id,
         agent_name
       ) do
    # 1. Build system prompt via Compositor
    system_prompt =
      agent_state.system_prompt || Compositor.assemble(agent_def, model_name)

    # 2. Get history
    history = agent_state.message_history || []

    # 3. Build messages
    messages =
      [%{role: "system", content: system_prompt}] ++
        history ++
        [%{role: "user", content: user_message}]

    # 4. Get tool schemas
    tools = get_tool_schemas(agent_def)

    # 5. Fire :agent_run_start callback
    Callbacks.dispatch(:agent_run_start, [agent_name, model_name, session_id])

    # Handle async option
    result =
      if Keyword.get(opts, :async) do
        try do
          {:ok, _pid} =
            Task.Supervisor.start_child(Mana.TaskSupervisor, fn ->
              do_execute_loop(
                messages,
                model_name,
                tools,
                opts,
                session_id,
                agent_name,
                user_message
              )
            end)

          {:ok, :async_started}
        catch
          :exit, _ ->
            # Task.Supervisor not available, run synchronously
            do_execute_loop(
              messages,
              model_name,
              tools,
              opts,
              session_id,
              agent_name,
              user_message
            )
        end
      else
        do_execute_loop(
          messages,
          model_name,
          tools,
          opts,
          session_id,
          agent_name,
          user_message
        )
      end

    stop_meta = %{agent_name: agent_name, model: model_name, session_id: session_id}

    case result do
      {:ok, _} = ok ->
        {ok, Map.put(stop_meta, :success, true)}

      {:error, reason} ->
        {{:error, reason}, Map.merge(stop_meta, %{success: false, error: inspect(reason)})}
    end
  end

  defp do_execute_loop(messages, model_name, tools, opts, session_id, agent_name, user_message) do
    # 6. Execute the loop
    case execute_loop(messages, model_name, tools, opts) do
      {:ok, response_text, _final_messages} ->
        # 7. Save to Session.Store
        save_session(session_id, user_message, response_text)

        # 8. Fire :agent_run_end callback
        Callbacks.dispatch(:agent_run_end, [
          agent_name,
          model_name,
          session_id,
          true,
          nil,
          response_text,
          %{}
        ])

        {:ok, response_text}

      {:error, reason} ->
        Callbacks.dispatch(:agent_run_end, [
          agent_name,
          model_name,
          session_id,
          false,
          reason,
          nil,
          %{}
        ])

        {:error, reason}
    end
  end

  @doc """
  Run agent with streaming — returns a Stream.

  ## Parameters

  - `agent_server` - PID of the agent server
  - `user_message` - The user message to send to the agent
  - `opts` - Keyword list of options:
    - `:max_iterations` - Maximum tool call iterations (default: 10)
    - `:handler` - Stream handler module (default: Mana.Streaming.ConsoleHandler)

  ## Returns

  An `Enumerable.t()` that yields stream events.

  ## Examples

      {:ok, pid} = Mana.Agent.Server.start_link(agent_def: agent_def)
      stream = Mana.Agent.Runner.stream(pid, "What is Elixir?")
      Enum.each(stream, fn {:part_delta, _id, content} -> IO.write(content) end)

  """
  @spec stream(pid() | map(), String.t(), keyword()) :: Enumerable.t()
  def stream(agent_server, user_message, opts \\ [])

  def stream(agent_pid, user_message, opts) when is_pid(agent_pid) do
    agent_state = Server.get_state(agent_pid)
    stream_from_state(agent_state, user_message, opts)
  end

  def stream(agent_state, user_message, opts) when is_map(agent_state) do
    stream_from_state(agent_state, user_message, opts)
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp execute_loop(messages, model_name, tools, opts, iterations \\ 0) do
    max_iterations = Keyword.get(opts, :max_iterations, 10)

    if iterations >= max_iterations do
      {:error, :max_iterations_exceeded}
    else
      # Get provider from model settings
      settings = Settings.make(model_name)
      provider = Settings.provider_module(settings)

      # Call provider.complete
      provider_opts = build_provider_opts(tools, opts)

      case provider.complete(messages, model_name, provider_opts) do
        {:ok, %{content: content, tool_calls: tool_calls}}
        when tool_calls != [] and
               tool_calls != nil ->
          # Has tool calls — execute them and loop
          tool_messages = execute_tool_calls(tool_calls, opts)

          # Build new messages with tool results
          assistant_msg = %{
            role: "assistant",
            content: content || "",
            tool_calls: tool_calls
          }

          new_messages = messages ++ [assistant_msg] ++ tool_messages

          # History compaction check
          new_messages = maybe_compact(new_messages, opts)

          execute_loop(new_messages, model_name, tools, opts, iterations + 1)

        {:ok, %{content: content}} ->
          # Final text response
          {:ok, content, messages ++ [%{role: "assistant", content: content}]}

        {:error, reason} ->
          {:error, reason}
      end
    end
  end

  defp stream_from_state(agent_state, user_message, opts) do
    agent_def = agent_state.agent_def
    model_name = agent_state.model_name
    session_id = agent_state.session_id || generate_session_id()

    system_prompt = agent_state.system_prompt
    history = agent_state.message_history || []

    messages =
      [%{role: "system", content: system_prompt}] ++
        history ++
        [%{role: "user", content: user_message}]

    tools = get_tool_schemas(agent_def)
    handler_module = Keyword.get(opts, :handler, Mana.Streaming.ConsoleHandler)
    handler = handler_module.new(session_id: session_id)

    agent_name = agent_def[:name] || "agent"

    # Fire :agent_run_start callback
    Callbacks.dispatch(:agent_run_start, [agent_name, model_name, session_id])

    # Emit telemetry start event
    start_time = System.monotonic_time()

    stream_meta = %{agent_name: agent_name, model: model_name, session_id: session_id}

    :telemetry.execute(
      @telemetry_prefix ++ [:start],
      %{system_time: System.system_time()},
      stream_meta
    )

    Stream.resource(
      fn ->
        %{
          messages: messages,
          iteration: 0,
          handler: handler,
          handler_module: handler_module,
          session_id: session_id,
          agent_name: agent_name,
          user_message: user_message,
          tools: tools,
          opts: opts,
          model_name: model_name,
          telemetry_start_time: start_time,
          telemetry_emitted: false
        }
      end,
      &stream_next/1,
      fn
        %{telemetry_emitted: true} ->
          :ok

        state when is_map(state) ->
          # Cleanup — fire agent_run_end and emit telemetry stop
          Callbacks.dispatch(:agent_run_end, [
            state.agent_name,
            state.model_name,
            state.session_id,
            true,
            nil,
            nil,
            %{}
          ])

          emit_stream_telemetry_stop(state, nil)

        _ ->
          :ok
      end
    )
  end

  defp emit_stream_telemetry_stop(state, final_content) do
    duration = System.monotonic_time() - state.telemetry_start_time

    stop_meta = %{
      agent_name: state.agent_name,
      model: state.model_name,
      session_id: state.session_id,
      success: true
    }

    extra = if final_content, do: %{response_length: String.length(final_content)}, else: %{}

    :telemetry.execute(
      @telemetry_prefix ++ [:stop],
      Map.merge(%{duration: duration}, extra),
      stop_meta
    )
  end

  defp emit_stream_telemetry_exception(state, reason) do
    duration = System.monotonic_time() - state.telemetry_start_time

    :telemetry.execute(
      @telemetry_prefix ++ [:exception],
      %{duration: duration},
      %{
        agent_name: state.agent_name,
        model: state.model_name,
        session_id: state.session_id,
        kind: :error,
        reason: reason,
        stacktrace: []
      }
    )
  end

  defp stream_next(%{iteration: iter, opts: opts} = state) do
    max_iterations = Keyword.get(opts, :max_iterations, 10)

    if iter >= max_iterations do
      {:halt, state}
    else
      do_stream_iteration(state)
    end
  end

  defp do_stream_iteration(state) do
    settings = Settings.make(state.model_name)
    provider = Settings.provider_module(settings)
    provider_opts = build_provider_opts(state.tools, state.opts)

    stream = provider.stream(state.messages, state.model_name, provider_opts)

    case process_stream(stream, state.handler_module, state.handler, state.session_id) do
      {:ok, {events, final_content, tool_calls}} ->
        if tool_calls != [] and tool_calls != nil do
          # Execute tool calls and continue loop
          tool_messages = execute_tool_calls(tool_calls, state.opts)

          assistant_msg = %{
            role: "assistant",
            content: final_content,
            tool_calls: tool_calls
          }

          new_messages = state.messages ++ [assistant_msg] ++ tool_messages

          # Check compaction
          new_messages = maybe_compact(new_messages, state.opts)

          new_state = %{
            state
            | messages: new_messages,
              iteration: state.iteration + 1,
              handler: state.handler
          }

          {events, new_state}
        else
          # Final response - save session and halt
          save_session(state.session_id, state.user_message, final_content)

          Callbacks.dispatch(:agent_run_end, [
            state.agent_name,
            state.model_name,
            state.session_id,
            true,
            nil,
            final_content,
            %{}
          ])

          # Emit telemetry stop for successful stream completion
          emit_stream_telemetry_stop(state, final_content)

          # Append final assistant message to events
          final_events = events ++ [{:done, final_content}]

          {final_events, %{state | telemetry_emitted: true}}
        end

      {:error, reason, partial_events} ->
        # Propagate streaming error - fire callback with error info
        Callbacks.dispatch(:agent_run_end, [
          state.agent_name,
          state.model_name,
          state.session_id,
          false,
          reason,
          nil,
          %{streaming_error: true, partial_event_count: length(partial_events)}
        ])

        # Emit telemetry exception for stream error
        emit_stream_telemetry_exception(state, reason)

        # Return error event to stream consumer
        error_events = partial_events ++ [{:error, reason}]
        {error_events, %{state | telemetry_emitted: true}}
    end
  end

  defp process_stream(stream, handler_module, handler, _session_id) do
    result =
      Enum.reduce(stream, {[], "", []}, fn event, {evts, content, tc} = acc ->
        case event do
          {:part_start, type, meta} ->
            part_id = generate_part_id()
            {:ok, _new_handler} = handler_module.handle_part_start(handler, part_id, type, meta)

            {evts ++ [{:part_start, part_id, type, meta}], content, tc}

          {:part_delta, _type, delta_content} ->
            part_id = get_current_part_id(handler)
            {:ok, _new_handler} = handler_module.handle_part_delta(handler, part_id, delta_content)

            {evts ++ [{:part_delta, part_id, delta_content}], content <> delta_content, tc}

          {:part_end, _type} ->
            part_id = get_current_part_id(handler)
            {:ok, _new_handler} = handler_module.handle_part_end(handler, part_id, %{})

            {evts ++ [{:part_end, part_id}], content, tc}

          {:tool_call, tool_call} ->
            {evts, content, tc ++ [tool_call]}

          {:error, reason} ->
            # Propagate error by throwing with accumulated state
            throw({:streaming_error, reason, evts, content, tc})

          _ ->
            acc
        end
      end)

    {:ok, result}
  catch
    {:streaming_error, reason, evts, _content, _tc} ->
      # Return error with partial results for debugging/retries
      {:error, reason, evts}
  end

  defp execute_tool_calls(tool_calls, _opts) do
    Enum.map(tool_calls, fn tool_call ->
      tool_name = get_tool_name(tool_call)
      args = get_tool_args(tool_call)
      tool_call_id = get_tool_call_id(tool_call)

      # Fire :pre_tool_call callback
      Callbacks.dispatch(:pre_tool_call, [tool_name, args, %{}])

      start_time = System.monotonic_time(:millisecond)

      # Execute via Tools.Registry
      result =
        case ToolsRegistry.execute(tool_name, args) do
          {:ok, result} -> Jason.encode!(%{result: result})
          {:error, reason} -> Jason.encode!(%{error: inspect(reason)})
        end

      end_time = System.monotonic_time(:millisecond)
      duration_ms = end_time - start_time

      # Fire :post_tool_call callback
      Callbacks.dispatch(:post_tool_call, [tool_name, args, result, duration_ms, %{}])

      %{
        role: "tool",
        tool_call_id: tool_call_id,
        content: result
      }
    end)
  end

  defp get_tool_schemas(agent_def) do
    available = Map.get(agent_def, :available_tools, []) || []
    ToolsRegistry.tool_definitions(List.first(available, ""))
  end

  defp build_provider_opts(tools, opts) do
    base_opts = []
    base_opts = if tools != [], do: Keyword.put(base_opts, :tools, tools), else: base_opts

    base_opts =
      case Keyword.get(opts, :temperature) do
        nil -> base_opts
        temp -> Keyword.put(base_opts, :temperature, temp)
      end

    base_opts =
      case Keyword.get(opts, :max_tokens) do
        nil -> base_opts
        tokens -> Keyword.put(base_opts, :max_tokens, tokens)
      end

    base_opts
  end

  defp maybe_compact(messages, opts) do
    if Compaction.should_compact?(messages) do
      Compaction.compact(messages, opts)
    else
      messages
    end
  end

  defp save_session(session_id, user_msg, response) do
    Store.append(session_id, %{role: "user", content: user_msg})
    Store.append(session_id, %{role: "assistant", content: response})
  end

  defp generate_session_id do
    "session-" <> Base.encode16(:crypto.strong_rand_bytes(8), case: :lower)
  end

  defp generate_part_id do
    "part-" <> Base.encode16(:crypto.strong_rand_bytes(4), case: :lower)
  end

  defp get_current_part_id(_handler) do
    # In a real implementation, this would track the current active part
    # For now, we generate a consistent ID based on time
    "part-current"
  end

  # Tool call parsing helpers - handle different API formats
  defp get_tool_name(%{function: %{name: name}}), do: name
  defp get_tool_name(%{"function" => %{"name" => name}}), do: name
  defp get_tool_name(%{name: name}), do: name
  defp get_tool_name(%{"name" => name}), do: name
  defp get_tool_name(_), do: "unknown"

  defp get_tool_args(tool_call) when is_map(tool_call) do
    raw_args = extract_raw_args(tool_call)
    parse_args(raw_args)
  end

  defp get_tool_args(_), do: %{}

  defp extract_raw_args(%{function: %{arguments: args}}), do: args
  defp extract_raw_args(%{"function" => %{"arguments" => args}}), do: args
  defp extract_raw_args(%{arguments: args}), do: args
  defp extract_raw_args(%{"arguments" => args}), do: args
  defp extract_raw_args(_), do: "{}"

  defp parse_args(args) when is_binary(args) do
    case Jason.decode(args) do
      {:ok, decoded} -> decoded
      _ -> %{}
    end
  end

  defp parse_args(args), do: args || %{}

  defp get_tool_call_id(%{id: id}), do: id
  defp get_tool_call_id(%{"id" => id}), do: id
  defp get_tool_call_id(_), do: generate_part_id()
end
