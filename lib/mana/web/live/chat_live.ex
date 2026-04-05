defmodule Mana.Web.Live.ChatLive do
  @moduledoc """
  LiveView for the Mana chat interface.

  Provides a real-time chat experience with:
  - Message history per session
  - Agent interaction through natural language
  - Command dispatch with "/command" syntax
  - Streaming response display
  - PubSub integration for real-time updates

  ## Architecture

  - Each socket connection has a unique session_id
  - Messages are stored in socket assigns
  - Agent execution happens in async tasks
  - PubSub broadcasts stream chunks for real-time updates

  ## Events

  - "send" - Submit a new message
  - "update_input" - Update the input field value

  ## Example Usage

      # Navigate to http://localhost:4000
      # Type messages naturally or use /commands
      # Messages persist for the session duration

  """

  use Phoenix.LiveView

  require Logger

  alias Mana.Agent.Runner
  alias Mana.Agent.Server, as: AgentServer
  alias Mana.Agents.Registry, as: AgentsRegistry
  alias Mana.Commands.Registry

  @impl true
  def mount(_params, _session, socket) do
    session_id = generate_session_id()

    # Subscribe to PubSub for this session
    Phoenix.PubSub.subscribe(:mana_pubsub, "session:#{session_id}")

    {:ok,
     assign(socket,
       session_id: session_id,
       messages: [],
       input: "",
       thinking: false,
       stream_output: "",
       agent_pid: nil
     )}
  end

  @impl true
  def handle_event("send", %{"message" => ""}, socket) do
    # Ignore empty messages
    {:noreply, socket}
  end

  def handle_event("send", %{"message" => message}, socket) do
    messages = socket.assigns.messages ++ [%{role: "user", content: message}]

    socket =
      assign(socket,
        messages: messages,
        input: "",
        thinking: true,
        stream_output: ""
      )

    agent_pid = socket.assigns.agent_pid

    Task.async(fn ->
      if String.starts_with?(message, "/") do
        dispatch_command(message)
      else
        run_agent(socket.assigns.session_id, message, agent_pid)
      end
    end)

    {:noreply, socket}
  end

  def handle_event("update_input", %{"value" => value}, socket) do
    {:noreply, assign(socket, input: value)}
  end

  @impl true
  def handle_info({ref, {:command_result, result}}, socket) when is_reference(ref) do
    messages = socket.assigns.messages ++ [%{role: "assistant", content: result}]
    {:noreply, assign(socket, messages: messages, thinking: false)}
  end

  def handle_info({ref, {:command_error, reason}}, socket) when is_reference(ref) do
    messages =
      socket.assigns.messages ++ [%{role: "assistant", content: "Error: #{reason}"}]

    {:noreply, assign(socket, messages: messages, thinking: false)}
  end

  def handle_info({ref, {:new_agent, pid, result}}, socket) when is_reference(ref) do
    socket = assign(socket, agent_pid: pid)
    handle_agent_result(socket, result)
  end

  def handle_info({ref, {:agent_result, content}}, socket) when is_reference(ref) do
    handle_agent_result(socket, {:agent_result, content})
  end

  def handle_info({ref, {:agent_error, reason}}, socket) when is_reference(ref) do
    handle_agent_result(socket, {:agent_error, reason})
  end

  def handle_info({:DOWN, _ref, :process, _pid, _reason}, socket) do
    # Task completed normally
    {:noreply, socket}
  end

  def handle_info({:stream_chunk, _type, chunk}, socket) do
    # Append stream chunk to current output
    {:noreply, assign(socket, stream_output: socket.assigns.stream_output <> chunk)}
  end

  @impl true
  def render(assigns) do
    ~H"""
    <div class="chat-container">
      <h1>Mana Chat</h1>

      <div class="messages" id="messages">
        <%= for msg <- @messages do %>
          <div class={["message", msg.role]}>
            <strong><%= msg.role %>:</strong>
            <pre><%= msg.content %></pre>
          </div>
        <% end %>

        <%= if @thinking do %>
          <div class="message thinking">
            <em>Thinking...</em>
          </div>
        <% end %>

        <%= if @stream_output != "" do %>
          <div class="message assistant streaming">
            <pre><%= @stream_output %></pre>
          </div>
        <% end %>
      </div>

      <form phx-submit="send" class="chat-form">
        <input
          type="text"
          name="message"
          value={@input}
          phx-change="update_input"
          placeholder="Type a message or /command"
          autocomplete="off"
          autofocus
        />
        <button type="submit">Send</button>
      </form>
    </div>

    <style>
      .chat-container {
        max-width: 800px;
        margin: 0 auto;
        padding: 20px;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }

      h1 {
        color: #333;
        border-bottom: 2px solid #6366f1;
        padding-bottom: 10px;
      }

      .messages {
        min-height: 400px;
        max-height: 600px;
        overflow-y: auto;
        border: 1px solid #e5e7eb;
        border-radius: 8px;
        padding: 16px;
        margin-bottom: 16px;
        background: #f9fafb;
      }

      .message {
        margin-bottom: 12px;
        padding: 12px;
        border-radius: 8px;
      }

      .message.user {
        background: #e0e7ff;
        margin-left: 20%;
      }

      .message.assistant {
        background: white;
        border: 1px solid #e5e7eb;
        margin-right: 20%;
      }

      .message.thinking {
        background: #fef3c7;
        color: #92400e;
        font-style: italic;
      }

      .message.streaming {
        background: #f3f4f6;
        border-left: 4px solid #6366f1;
      }

      .message pre {
        margin: 8px 0 0 0;
        white-space: pre-wrap;
        word-wrap: break-word;
        font-family: inherit;
      }

      .chat-form {
        display: flex;
        gap: 8px;
      }

      .chat-form input {
        flex: 1;
        padding: 12px;
        border: 2px solid #e5e7eb;
        border-radius: 8px;
        font-size: 16px;
      }

      .chat-form input:focus {
        outline: none;
        border-color: #6366f1;
      }

      .chat-form button {
        padding: 12px 24px;
        background: #6366f1;
        color: white;
        border: none;
        border-radius: 8px;
        font-size: 16px;
        cursor: pointer;
      }

      .chat-form button:hover {
        background: #4f46e5;
      }
    </style>
    """
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp generate_session_id do
    :crypto.strong_rand_bytes(16) |> Base.encode16(case: :lower)
  end

  defp dispatch_command(message) do
    # Remove leading slash and split into command and args
    [cmd | args] = String.split(String.trim_leading(message, "/"), " ", parts: 2)
    args = if args == [], do: [], else: [hd(args)]
    full_cmd = "/#{cmd}"

    case Registry.dispatch(full_cmd, args, %{}) do
      :ok -> {:command_result, "Command executed: /#{cmd}"}
      {:ok, result} -> {:command_result, to_string(result)}
      {:error, reason} -> {:command_error, to_string(reason)}
    end
  rescue
    error ->
      Logger.error("Command dispatch error: #{inspect(error)}")
      {:command_error, "Failed to execute command"}
  end

  defp run_agent(session_id, message, agent_pid) do
    if agent_pid && Process.alive?(agent_pid) do
      # Reuse existing agent server
      execute_agent_run(agent_pid, message, session_id)
    else
      # Create new agent server
      case start_agent_server(session_id) do
        {:ok, pid} -> {:new_agent, pid, execute_agent_run(pid, message, session_id)}
        {:error, reason} -> {:agent_error, reason}
      end
    end
  end

  defp start_agent_server(session_id) do
    case AgentsRegistry.current_agent(session_id) do
      nil ->
        {:error, "No agent available for session"}

      agent ->
        case AgentServer.start_link(agent_def: agent, session_id: session_id) do
          {:ok, pid} ->
            {:ok, pid}

          {:error, reason} ->
            Logger.error("Failed to start agent server: #{inspect(reason)}")
            {:error, "Failed to initialize agent"}
        end
    end
  end

  defp execute_agent_run(pid, message, session_id) do
    case Runner.run(pid, message, session_id: session_id) do
      {:ok, content} -> {:agent_result, content}
      {:error, reason} -> {:agent_error, inspect(reason)}
    end
  rescue
    error ->
      Logger.error("Agent run error: #{inspect(error)}")
      {:agent_error, "Agent execution failed"}
  end

  defp handle_agent_result(socket, {:agent_result, content}) do
    messages = socket.assigns.messages ++ [%{role: "assistant", content: content}]
    {:noreply, assign(socket, messages: messages, thinking: false)}
  end

  defp handle_agent_result(socket, {:agent_error, reason}) do
    messages = socket.assigns.messages ++ [%{role: "assistant", content: "Error: #{reason}"}]
    {:noreply, assign(socket, messages: messages, thinking: false)}
  end
end
