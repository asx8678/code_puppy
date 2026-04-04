defmodule Mana.MessageBus do
  @moduledoc """
  Named GenServer that manages message flow for the Mana system.

  The MessageBus handles:
  - Message emission (async broadcasts to listeners)
  - Request/response flow (blocking calls for user input)
  - Listener subscription management

  ## Architecture

  - Named GenServer (`name: __MODULE__`) for easy discovery
  - Listeners subscribe via `add_listener/1` to receive all messages
  - Messages are emitted via `emit/1` (async cast)
  - User input requests block via GenServer.call with 300s timeout
  - Responses provided via `provide_response/2` to unblock waiting callers

  ## Usage

  ### Starting the Bus

      Mana.MessageBus.start_link([])

  ### Emitting Messages

      # Emit any message struct
      Mana.MessageBus.emit(message)

      # Convenience functions for text messages
      Mana.MessageBus.emit_text("Hello", role: :user)
      Mana.MessageBus.emit_info("Operation started")
      Mana.MessageBus.emit_warning("Low disk space")
      Mana.MessageBus.emit_error("Connection failed")

  ### Requesting User Input

      # Blocks until user provides response (300s timeout)
      {:ok, response} = Mana.MessageBus.request_input("Enter your name:")
      {:ok, confirmed} = Mana.MessageBus.request_confirmation("Delete file?")
      {:ok, choice} = Mana.MessageBus.request_selection("Pick one:", ["A", "B", "C"])

  ### Providing Responses (UI Layer)

      # UI calls this when user provides input
      :ok = Mana.MessageBus.provide_response(request_id, user_response)

  ### Managing Listeners

      Mana.MessageBus.add_listener(self())
      Mana.MessageBus.remove_listener(self())
  """

  use GenServer

  require Logger

  alias Mana.Message
  alias Mana.MessageBus.RequestTracker

  @default_request_timeout 300_000

  @doc """
  Starts the MessageBus GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Returns the child specification for supervision trees.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :permanent
    }
  end

  @doc """
  Emits a message to all registered listeners.

  The message is broadcast asynchronously via GenServer.cast.
  """
  @spec emit(struct()) :: :ok
  def emit(message) do
    GenServer.cast(__MODULE__, {:emit, message})
  end

  @doc """
  Convenience function to emit a text message.

  ## Options

  - `:role` - `:user`, `:assistant`, or `:system` (default: `:system`)
  - `:session_id` - Optional session identifier

  ## Examples

      Mana.MessageBus.emit_text("Hello world", role: :assistant)
      Mana.MessageBus.emit_text("Task complete", role: :system, session_id: "abc123")
  """
  @spec emit_text(String.t(), keyword()) :: :ok
  def emit_text(content, opts \\ []) do
    role = Keyword.get(opts, :role, :system)
    session_id = Keyword.get(opts, :session_id)

    message =
      Message.new(:text, %{
        content: content,
        role: role,
        session_id: session_id
      })

    emit(message)
  end

  @doc """
  Emits an informational text message.
  """
  @spec emit_info(String.t(), keyword()) :: :ok
  def emit_info(content, opts \\ []) do
    emit_text(content, Keyword.put(opts, :role, :system))
  end

  @doc """
  Emits a warning text message.
  """
  @spec emit_warning(String.t(), keyword()) :: :ok
  def emit_warning(content, opts \\ []) do
    emit_text("⚠️  #{content}", Keyword.put(opts, :role, :system))
  end

  @doc """
  Emits an error text message.
  """
  @spec emit_error(String.t(), keyword()) :: :ok
  def emit_error(content, opts \\ []) do
    emit_text("❌ #{content}", Keyword.put(opts, :role, :system))
  end

  @doc """
  Requests text input from the user.

  Blocks via GenServer.call until the user provides a response
  or the timeout (300 seconds) is reached.

  ## Options

  - `:session_id` - Optional session identifier
  - `:timeout` - Custom timeout in milliseconds (default: 300_000)

  ## Returns

  - `{:ok, response}` - User's input string
  - `{:error, :timeout}` - Request timed out
  """
  @spec request_input(String.t(), keyword()) :: {:ok, String.t()} | {:error, :timeout}
  def request_input(prompt, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, @default_request_timeout)
    session_id = Keyword.get(opts, :session_id)

    GenServer.call(__MODULE__, {:request, :input, prompt, session_id}, timeout)
  catch
    :exit, {:timeout, _} ->
      {:error, :timeout}
  end

  @doc """
  Requests a yes/no confirmation from the user.

  Blocks via GenServer.call until the user confirms/cancels
  or the timeout (300 seconds) is reached.

  ## Options

  - `:session_id` - Optional session identifier
  - `:timeout` - Custom timeout in milliseconds (default: 300_000)

  ## Returns

  - `{:ok, true}` - User confirmed (yes)
  - `{:ok, false}` - User cancelled (no)
  - `{:error, :timeout}` - Request timed out
  """
  @spec request_confirmation(String.t(), keyword()) :: {:ok, boolean()} | {:error, :timeout}
  def request_confirmation(prompt, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, @default_request_timeout)
    session_id = Keyword.get(opts, :session_id)

    GenServer.call(__MODULE__, {:request, :confirmation, prompt, session_id}, timeout)
  catch
    :exit, {:timeout, _} ->
      {:error, :timeout}
  end

  @doc """
  Requests a selection from a list of choices.

  Blocks via GenServer.call until the user makes a selection
  or the timeout (300 seconds) is reached.

  ## Options

  - `:session_id` - Optional session identifier
  - `:timeout` - Custom timeout in milliseconds (default: 300_000)

  ## Returns

  - `{:ok, choice}` - Selected value from the choices list
  - `{:error, :timeout}` - Request timed out
  """
  @spec request_selection(String.t(), [String.t()], keyword()) ::
          {:ok, String.t()} | {:error, :timeout}
  def request_selection(prompt, choices, opts \\ []) do
    timeout = Keyword.get(opts, :timeout, @default_request_timeout)
    session_id = Keyword.get(opts, :session_id)

    GenServer.call(__MODULE__, {:request, :selection, prompt, choices, session_id}, timeout)
  catch
    :exit, {:timeout, _} ->
      {:error, :timeout}
  end

  @doc """
  Provides a response to a pending user interaction request.

  Called by the UI layer when the user provides input. Unblocks
  the waiting request_input/confirmation/selection call.

  ## Returns

  - `:ok` - Response was successfully delivered
  - `{:error, :not_found}` - Request ID not found (may have timed out)
  """
  @spec provide_response(String.t(), any()) :: :ok | {:error, :not_found}
  def provide_response(request_id, response) do
    GenServer.call(__MODULE__, {:provide_response, request_id, response})
  end

  @doc """
  Adds a process as a message listener.

  The listener process will receive `{:message, message}` tuples
  for all messages emitted on the bus.
  """
  @spec add_listener(pid()) :: :ok
  def add_listener(pid) do
    GenServer.call(__MODULE__, {:add_listener, pid})
  end

  @doc """
  Removes a process from the message listeners.
  """
  @spec remove_listener(pid()) :: :ok
  def remove_listener(pid) do
    GenServer.call(__MODULE__, {:remove_listener, pid})
  end

  @doc """
  Lists all pending request IDs.
  """
  @spec list_pending_requests() :: [String.t()]
  def list_pending_requests do
    GenServer.call(__MODULE__, :list_pending_requests)
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    state = %{
      listeners: MapSet.new(),
      pending_requests: %{},
      request_counter: 0
    }

    {:ok, state}
  end

  @impl true
  def handle_cast({:emit, message}, state) do
    # Broadcast to all listeners
    Enum.each(state.listeners, fn pid ->
      send(pid, {:message, message})
    end)

    # Log for debugging
    Logger.debug("Message emitted: #{inspect(message)}")

    {:noreply, state}
  end

  @impl true
  def handle_call({:request, type, prompt, session_id}, from, state) do
    request_id = RequestTracker.new_request_id()

    # Create and emit the user interaction request message
    message =
      Message.new(:user_interaction, %{
        prompt: prompt,
        interaction_type: type,
        session_id: session_id,
        id: request_id
      })

    # Track the pending request
    new_state = RequestTracker.track(state, request_id, from, type)

    # Emit the message so listeners (UI) see it
    Enum.each(new_state.listeners, fn pid ->
      send(pid, {:message, message})
    end)

    # Note: We don't reply here - the caller blocks until provide_response is called
    {:noreply, new_state}
  end

  @impl true
  def handle_call({:request, :selection, prompt, choices, session_id}, from, state) do
    request_id = RequestTracker.new_request_id()

    # Create and emit the selection request message
    message =
      Message.new(:user_interaction, %{
        prompt: prompt,
        interaction_type: :selection,
        session_id: session_id,
        id: request_id,
        payload: %{choices: choices}
      })

    # Track the pending request with selection context
    new_state = RequestTracker.track(state, request_id, from, :selection)

    # Emit the message so listeners (UI) see it
    Enum.each(new_state.listeners, fn pid ->
      send(pid, {:message, message})
    end)

    {:noreply, new_state}
  end

  @impl true
  def handle_call({:provide_response, request_id, response}, _from, state) do
    case RequestTracker.resolve(state, request_id, response) do
      {:ok, new_state} ->
        {:reply, :ok, new_state}

      {:error, :not_found} ->
        {:reply, {:error, :not_found}, state}
    end
  end

  @impl true
  def handle_call({:add_listener, pid}, _from, state) do
    # Monitor the listener so we can clean up if it dies
    Process.monitor(pid)
    new_listeners = MapSet.put(state.listeners, pid)
    {:reply, :ok, %{state | listeners: new_listeners}}
  end

  @impl true
  def handle_call({:remove_listener, pid}, _from, state) do
    new_listeners = MapSet.delete(state.listeners, pid)
    {:reply, :ok, %{state | listeners: new_listeners}}
  end

  @impl true
  def handle_call(:list_pending_requests, _from, state) do
    {:reply, RequestTracker.list_pending(state), state}
  end

  @impl true
  def handle_info({:DOWN, _ref, :process, pid, _reason}, state) do
    # Clean up dead listener
    new_listeners = MapSet.delete(state.listeners, pid)
    {:noreply, %{state | listeners: new_listeners}}
  end

  @impl true
  def handle_info(_msg, state) do
    {:noreply, state}
  end
end
