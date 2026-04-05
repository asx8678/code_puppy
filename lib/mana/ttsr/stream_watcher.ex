defmodule Mana.TTSR.StreamWatcher do
  @moduledoc """
  GenServer that watches streaming events and triggers TTSR rules.

  Maintains per-scope ring buffers (512 chars) to catch patterns
  that straddle SSE chunk boundaries.
  """

  use GenServer

  require Logger

  alias Mana.TTSR.Rule

  @buffer_size 512
  @registry_name Mana.TTSR.Registry

  defstruct [
    :session_id,
    :rules,
    :current_scope,
    text_buffer: "",
    thinking_buffer: "",
    tool_buffer: "",
    current_turn: 0,
    triggered_rules: MapSet.new(),
    last_activity: nil,
    byte_buffer: <<>>
  ]

  @typedoc "StreamWatcher state"
  @type t :: %__MODULE__{
          session_id: String.t(),
          rules: [Rule.t()],
          current_scope: atom() | nil,
          text_buffer: String.t(),
          thinking_buffer: String.t(),
          tool_buffer: String.t(),
          current_turn: non_neg_integer(),
          triggered_rules: MapSet.t(String.t()),
          last_activity: DateTime.t() | nil,
          byte_buffer: binary()
        }

  # Client API

  @doc """
  Child spec for DynamicSupervisor — transient restart so crashes are
  restarted but normal exits are not.
  """
  def child_spec({session_id, rules}) do
    %{
      id: {__MODULE__, session_id},
      start: {__MODULE__, :start_link, [session_id, rules]},
      restart: :transient
    }
  end

  @doc """
  Starts a StreamWatcher for the given session.
  """
  @spec start_link(String.t(), [Rule.t()]) :: GenServer.on_start()
  def start_link(session_id, rules) do
    GenServer.start_link(
      __MODULE__,
      {session_id, rules},
      name: via_tuple(session_id)
    )
  end

  @doc """
  Starts a StreamWatcher under the DynamicSupervisor.
  """
  @spec start_supervised(String.t(), [Rule.t()]) :: DynamicSupervisor.on_start_child()
  def start_supervised(session_id, rules) do
    DynamicSupervisor.start_child(
      Mana.TTSR.WatcherSupervisor,
      {__MODULE__, {session_id, rules}}
    )
  end

  @doc """
  Stops a supervised StreamWatcher for the given session.
  """
  @spec stop(String.t()) :: :ok
  def stop(session_id) do
    case find_watcher(session_id) do
      nil ->
        :ok

      pid ->
        DynamicSupervisor.terminate_child(Mana.TTSR.WatcherSupervisor, pid)
        :ok
    end
  end

  @doc """
  Watches a stream event, updating buffers and checking for triggers.
  """
  @spec watch_event(String.t(), {atom(), any()}) :: :ok
  def watch_event(session_id, event) do
    case find_watcher(session_id) do
      nil -> :ok
      pid -> GenServer.cast(pid, {:stream_event, event})
    end
  end

  @doc """
  Returns all pending rules and clears their pending status.
  """
  @spec get_pending(String.t()) :: [Rule.t()]
  def get_pending(session_id) do
    case find_watcher(session_id) do
      nil -> []
      pid -> GenServer.call(pid, :get_pending)
    end
  end

  @doc """
  Increments the turn counter for a session.
  """
  @spec increment_turn(String.t()) :: :ok
  def increment_turn(session_id) do
    case find_watcher(session_id) do
      nil -> :ok
      pid -> GenServer.cast(pid, :increment_turn)
    end
  end

  @doc """
  Returns the current watcher pid for a session, if any.
  """
  @spec find_watcher(String.t()) :: pid() | nil
  def find_watcher(session_id) do
    case Registry.lookup(@registry_name, session_id) do
      [{pid, _}] ->
        if Process.alive?(pid), do: pid, else: nil

      [] ->
        nil
    end
  end

  @doc """
  Returns the last activity timestamp for a session's watcher, if any.
  """
  @spec get_last_activity(String.t()) :: DateTime.t() | nil
  def get_last_activity(session_id) do
    case find_watcher(session_id) do
      nil -> nil
      pid -> GenServer.call(pid, :get_last_activity)
    end
  end

  # Server Callbacks

  @impl true
  def init({session_id, rules}) do
    {:ok, %__MODULE__{session_id: session_id, rules: rules, last_activity: DateTime.utc_now()}}
  end

  @impl true
  def handle_cast({:stream_event, event}, state) do
    new_state = %{state | last_activity: DateTime.utc_now()}
    handle_stream_event(event, new_state)
  end

  def handle_cast(:increment_turn, state) do
    # Reset buffers and increment turn
    {:noreply,
     %{
       state
       | current_turn: state.current_turn + 1,
         text_buffer: "",
         thinking_buffer: "",
         tool_buffer: "",
         byte_buffer: <<>>
     }}
  end

  @impl true
  def handle_call(:get_pending, _from, state) do
    pending = Enum.filter(state.rules, & &1.pending)

    # Clear pending flags
    new_rules =
      Enum.map(state.rules, fn rule ->
        %{rule | pending: false}
      end)

    {:reply, pending, %{state | rules: new_rules}}
  end

  @impl true
  def handle_call(:get_last_activity, _from, state) do
    {:reply, state.last_activity, state}
  end

  # Private Functions

  defp handle_stream_event({:part_delta, _part_id, content}, state) do
    # Use current scope if tracked, otherwise default to :text
    scope = state.current_scope || :text
    handle_stream_content(state, scope, content)
  end

  defp handle_stream_event({:part_start, _part_id, type, _meta}, state) do
    # Track scope type for subsequent deltas
    {:noreply, Map.put(state, :current_scope, type)}
  end

  defp handle_stream_event({:part_end, _part_id, _meta}, state) do
    {:noreply, Map.put(state, :current_scope, nil)}
  end

  defp handle_stream_event(_other_event, state) do
    {:noreply, state}
  end

  defp push_to_buffer(buffer, char) do
    new = buffer <> char

    if String.length(new) > @buffer_size do
      String.slice(new, -@buffer_size, @buffer_size)
    else
      new
    end
  end

  defp check_rules_for_scope(rules, buffer, scope, current_turn) do
    Enum.map(rules, fn rule ->
      cond do
        rule.pending ->
          rule

        rule.scope not in [scope, :all] ->
          rule

        not Rule.eligible?(rule, current_turn) ->
          rule

        Regex.match?(rule.trigger, buffer) ->
          Logger.debug("TTSR rule '#{rule.name}' triggered in scope #{scope}")
          %{rule | pending: true, triggered_at_turn: current_turn}

        true ->
          rule
      end
    end)
  end

  # Splits binary into {valid_utf8_prefix, trailing_incomplete_bytes}
  # This handles the case where an SSE chunk boundary falls in the middle
  # of a multi-byte UTF-8 codepoint.
  @doc false
  defp split_valid_utf8(bin) when is_binary(bin) do
    if String.valid?(bin) do
      {bin, <<>>}
    else
      trim_invalid_trailing(bin)
    end
  end

  defp trim_invalid_trailing(bin) do
    size = byte_size(bin)
    # UTF-8 codepoints are max 4 bytes, so check last 1-4 bytes
    trim =
      Enum.find(1..min(4, size), fn n ->
        prefix = binary_part(bin, 0, size - n)
        String.valid?(prefix)
      end)

    case trim do
      nil ->
        # Entire binary is invalid — buffer it all
        {"", bin}

      n ->
        prefix = binary_part(bin, 0, size - n)
        suffix = binary_part(bin, size - n, n)
        {prefix, suffix}
    end
  end

  defp handle_stream_content(state, scope, content) when is_binary(content) do
    # Prepend any leftover bytes from previous chunk
    full_content = state.byte_buffer <> content

    # Split into valid UTF-8 prefix + possibly-incomplete trailing bytes
    {valid, remainder} = split_valid_utf8(full_content)

    buffer_key =
      case scope do
        :thinking -> :thinking_buffer
        :tool -> :tool_buffer
        _ -> :text_buffer
      end

    buffer = Map.get(state, buffer_key, "")

    {new_buffer, new_rules} =
      if valid == "" do
        {buffer, state.rules}
      else
        Enum.reduce(String.graphemes(valid), {buffer, state.rules}, fn char, {buf, rules} ->
          updated_buffer = push_to_buffer(buf, char)
          checked_rules = check_rules_for_scope(rules, updated_buffer, scope, state.current_turn)
          {updated_buffer, checked_rules}
        end)
      end

    new_state =
      state
      |> Map.put(buffer_key, new_buffer)
      |> Map.put(:rules, new_rules)
      |> Map.put(:byte_buffer, remainder)

    {:noreply, new_state}
  end

  defp via_tuple(session_id) do
    {:via, Registry, {@registry_name, session_id}}
  end
end
