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

    case run(agent_state, user_message, opts) do
      {:ok, response} ->
        # Sync messages back to the Server
        Server.add_message(agent_pid, %{role: "user", content: user_message})
        Server.add_message(agent_pid, %{role: "assistant", content: response})
        {:ok, response}

      error ->
        error
    end
  end

  def run(agent_state, user_message, opts) when is_map(agent_state) do
    agent_def = agent_state.agent_def
    model_name = agent_state.model_name
    session_id = agent_state.session_id || generate_session_id()

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
    agent_name = agent_def[:name] || "agent"
    Callbacks.dispatch(:agent_run_start, [agent_name, model_name, session_id])

    # Handle async option
    if Keyword.get(opts, :async) do
      try do
        {:ok, _pid} =
          Task.Supervisor.start_child(Mana.TaskSupervisor, fn ->
            do_execute_loop(messages, model_name, tools, opts, session_id, agent_name, user_message)
          end)

        {:ok, :async_started}
      catch
        :exit, _ ->
          # Task.Supervisor not available, run synchronously
          do_execute_loop(messages, model_name, tools, opts, session_id, agent_name, user_message)
      end
    else
      do_execute_loop(messages, model_name, tools, opts, session_id, agent_name, user_message)
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
          model_name: model_name
        }
      end,
      &stream_next/1,
      fn state ->
        # Cleanup - fire agent_run_end if not already done
        # Handle both map state and :halt atom
        if is_map(state) do
          Callbacks.dispatch(:agent_run_end, [
            state.agent_name,
            state.model_name,
            state.session_id,
            true,
            nil,
            nil,
            %{}
          ])
        end

        :ok
      end
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

    {events, final_content, tool_calls} =
      process_stream(stream, state.handler_module, state.handler, state.session_id)

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

      # Append final assistant message to events
      final_events = events ++ [{:done, final_content}]

      {final_events, :halt}
    end
  end

  defp process_stream(stream, handler_module, handler, session_id) do
    {evts, content, tc, _part_id, _final_handler} =
      Enum.reduce(stream, {[], "", [], nil, handler}, fn event, {evts, content, tc, current_part_id, hdlr} ->
        case event do
          {:part_start, type, meta} ->
            part_id = generate_part_id()
            {:ok, new_handler} = handler_module.handle_part_start(hdlr, part_id, type, meta)

            Callbacks.dispatch(:stream_event, [
              :part_start,
              %{part_id: part_id, type: type, metadata: meta},
              session_id
            ])

            {evts ++ [{:part_start, part_id, type, meta}], content, tc, part_id, new_handler}

          {:part_delta, _type, delta_content} ->
            pid = current_part_id || "part-unknown"
            {:ok, new_handler} = handler_module.handle_part_delta(hdlr, pid, delta_content)

            Callbacks.dispatch(:stream_event, [
              :part_delta,
              %{part_id: pid, content: delta_content},
              session_id
            ])

            {evts ++ [{:part_delta, pid, delta_content}], content <> delta_content, tc, current_part_id, new_handler}

          {:part_end, _type} ->
            pid = current_part_id || "part-unknown"
            {:ok, new_handler} = handler_module.handle_part_end(hdlr, pid, %{})

            Callbacks.dispatch(:stream_event, [
              :part_end,
              %{part_id: pid},
              session_id
            ])

            {evts ++ [{:part_end, pid}], content, tc, nil, new_handler}

          {:tool_call, tool_call} ->
            {evts, content, tc ++ [tool_call], current_part_id, hdlr}

          {:error, _reason} ->
            {evts, content, tc, current_part_id, hdlr}

          _ ->
            {evts, content, tc, current_part_id, hdlr}
        end
      end)

    {evts, content, tc}
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

    if available == [] do
      []
    else
      Enum.flat_map(available, fn tool_name ->
        case ToolsRegistry.tool_definitions(tool_name) do
          tools when is_list(tools) -> tools
          _ -> []
        end
      end)
    end
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

  # Tool call parsing helpers - handle different API formats
  defp get_tool_name(%{"function" => %{"name" => name}}), do: name
  defp get_tool_name(%{function: %{name: name}}), do: name
  defp get_tool_name(%{"name" => name}), do: name
  defp get_tool_name(%{name: name}), do: name
  defp get_tool_name(_), do: "unknown"

  defp get_tool_args(tool_call) when is_map(tool_call) do
    raw_args = extract_raw_args(tool_call)
    parse_args(raw_args)
  end

  defp get_tool_args(_), do: %{}

  defp extract_raw_args(%{"function" => %{"arguments" => args}}), do: args
  defp extract_raw_args(%{function: %{arguments: args}}), do: args
  defp extract_raw_args(%{"arguments" => args}), do: args
  defp extract_raw_args(%{arguments: args}), do: args
  defp extract_raw_args(_), do: "{}"

  defp parse_args(args) when is_binary(args) do
    case Jason.decode(args) do
      {:ok, decoded} -> decoded
      _ -> %{}
    end
  end

  defp parse_args(args), do: args || %{}

  defp get_tool_call_id(%{"id" => id}), do: id
  defp get_tool_call_id(%{id: id}), do: id
  defp get_tool_call_id(_), do: generate_part_id()
end
