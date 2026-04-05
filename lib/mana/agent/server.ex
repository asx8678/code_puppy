defmodule Mana.Agent.Server do
  @moduledoc """
  GenServer for per-agent state management.

  A thin state layer that delegates logic to pure function modules:
  - History management → Mana.Agent.History
  - Compaction → Mana.Agent.Compaction
  - System prompt assembly → Mana.Prompt.Compositor

  ## Usage

      {:ok, pid} = Mana.Agent.Server.start_link(
        agent_def: %{name: "coder", system_prompt: "..."},
        model_name: "gpt-4",
        session_id: "session-123"
      )

      :ok = Mana.Agent.Server.add_message(pid, %{role: "user", content: "Hello"})
      history = Mana.Agent.Server.get_history(pid)

  ## State Structure

  - `:id` - Unique server identifier
  - `:agent_def` - Agent definition map
  - `:model_name` - Current model name
  - `:system_prompt` - Cached system prompt
  - `:message_history` - List of messages
  - `:history_hashes` - MapSet of message hashes for deduplication
  - `:compacted_hashes` - MapSet of hashes from compacted messages
  - `:session_id` - Optional session identifier
  - `:started_at` - When the server was started

  """

  use GenServer

  alias Mana.Agent.Compaction
  alias Mana.Agent.History
  alias Mana.Config
  alias Mana.Prompt.Compositor

  require Logger

  defstruct [
    :id,
    :agent_def,
    :model_name,
    :system_prompt,
    message_history: [],
    history_hashes: MapSet.new(),
    compacted_hashes: MapSet.new(),
    session_id: nil,
    started_at: nil
  ]

  @doc """
  Starts the agent server.

  ## Options

    - `:agent_def` - Required. Agent definition map
    - `:model_name` - Optional. Defaults to Config.global_model_name()
    - `:session_id` - Optional. Session identifier

  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts) do
    GenServer.start_link(__MODULE__, opts)
  end

  @doc "Returns the current server state (for debugging/monitoring)"
  @spec get_state(GenServer.server()) :: %__MODULE__{}
  def get_state(pid) do
    GenServer.call(pid, :get_state)
  end

  @doc "Adds a message to the history"
  @spec add_message(GenServer.server(), map()) :: :ok
  def add_message(pid, message) do
    GenServer.call(pid, {:add_message, message})
  end

  @doc "Returns the current message history"
  @spec get_history(GenServer.server()) :: [map()]
  def get_history(pid) do
    GenServer.call(pid, :get_history)
  end

  @doc """
  Compacts the message history.

  ## Options

  Passed to Mana.Agent.Compaction.compact/2:
    - `:max_tokens` - Maximum tokens to keep (default: 8000)

  """
  @spec compact_history(GenServer.server(), keyword()) :: :ok
  def compact_history(pid, opts \\ []) do
    GenServer.call(pid, {:compact, opts})
  end

  @doc "Changes the model and rebuilds the system prompt"
  @spec set_model(GenServer.server(), String.t()) :: :ok
  def set_model(pid, model_name) do
    GenServer.call(pid, {:set_model, model_name})
  end

  # GenServer callbacks

  @impl true
  def init(opts) do
    agent_def = Keyword.fetch!(opts, :agent_def)
    model_name = Keyword.get(opts, :model_name, Config.global_model_name())
    session_id = Keyword.get(opts, :session_id)

    system_prompt = Compositor.assemble(agent_def, model_name)

    state = %__MODULE__{
      id: generate_id(),
      agent_def: agent_def,
      model_name: model_name,
      system_prompt: system_prompt,
      session_id: session_id,
      started_at: DateTime.utc_now()
    }

    {:ok, state}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, state}
  end

  @impl true
  def handle_call({:add_message, message}, _from, state) do
    {deduped, new_hashes} = History.deduplicate([message], state.history_hashes)
    new_history = History.accumulate(state.message_history, deduped)

    new_state = %{
      state
      | message_history: new_history,
        history_hashes: new_hashes
    }

    {:reply, :ok, new_state}
  end

  @impl true
  def handle_call(:get_history, _from, state) do
    {:reply, state.message_history, state}
  end

  @impl true
  def handle_call({:compact, opts}, _from, state) do
    compacted = Compaction.compact(state.message_history, opts)

    new_hashes =
      Enum.reduce(compacted, state.compacted_hashes, fn msg, hashes ->
        MapSet.put(hashes, History.hash_message(msg))
      end)

    new_state = %{
      state
      | message_history: compacted,
        compacted_hashes: new_hashes
    }

    {:reply, :ok, new_state}
  end

  @impl true
  def handle_call({:set_model, model_name}, _from, state) do
    system_prompt = Compositor.assemble(state.agent_def, model_name)

    new_state = %{
      state
      | model_name: model_name,
        system_prompt: system_prompt
    }

    {:reply, :ok, new_state}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("[Mana.Agent.Server] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  defp generate_id do
    :crypto.strong_rand_bytes(8) |> Base.encode16(case: :lower)
  end
end
