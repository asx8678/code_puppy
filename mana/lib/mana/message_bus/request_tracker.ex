defmodule Mana.MessageBus.RequestTracker do
  @moduledoc """
  Pure helper module for request correlation tracking.

  Provides functions for generating request IDs, tracking pending
  requests, and resolving them with responses.

  This module is stateless and operates on the MessageBus state map.
  """

  @typedoc "Request tracking state"
  @type state :: %{
          listeners: MapSet.t(pid()),
          pending_requests: %{optional(String.t()) => pending_request()},
          request_counter: non_neg_integer()
        }

  @typedoc "Pending request entry"
  @type pending_request :: %{
          from: GenServer.from(),
          type: atom(),
          caller_pid: pid(),
          monitor_ref: reference(),
          timestamp: integer()
        }

  @doc """
  Generates a unique request ID.

  Uses the current timestamp and a random component for uniqueness.

  ## Examples

      iex> Mana.MessageBus.RequestTracker.new_request_id()
      "req_1678886400_abc123"
  """
  @spec new_request_id() :: String.t()
  def new_request_id do
    timestamp = System.system_time(:millisecond)
    random = :crypto.strong_rand_bytes(8) |> Base.encode16(case: :lower)
    "req_#{timestamp}_#{random}"
  end

  @doc """
  Tracks a new pending request in the state.

  ## Parameters

  - `state` - Current MessageBus state
  - `id` - Request ID (from `new_request_id/0`)
  - `from` - GenServer.from() tuple for replying later
  - `type` - Request type atom (e.g., `:input`, `:confirmation`)

  ## Returns

  Updated state with the tracked request.
  """
  @spec track(state(), String.t(), GenServer.from(), atom()) :: state()
  def track(state, id, from, type) do
    {caller_pid, _} = from
    monitor_ref = Process.monitor(caller_pid)
    timestamp = System.monotonic_time(:millisecond)

    pending =
      Map.put(state.pending_requests, id, %{
        from: from,
        type: type,
        caller_pid: caller_pid,
        monitor_ref: monitor_ref,
        timestamp: timestamp
      })

    %{state | pending_requests: pending}
  end

  @doc """
  Resolves a pending request with a response.

  Returns `{:ok, new_state}` if the request was found and resolved,
  or `{:error, :not_found}` if the request ID doesn't exist.

  When a request is resolved, the caller monitor is demonitored.
  """
  @spec resolve(state(), String.t(), any()) :: {:ok, state()} | {:error, :not_found}
  def resolve(state, id, response) do
    case Map.pop(state.pending_requests, id) do
      {%{from: from, type: _type, monitor_ref: ref}, remaining} ->
        # Demonitor the caller and reply to the waiting process
        Process.demonitor(ref, [:flush])
        GenServer.reply(from, {:ok, response})
        {:ok, %{state | pending_requests: remaining}}

      {nil, _pending} ->
        {:error, :not_found}
    end
  end

  @doc """
  Removes a pending request without sending a response.

  Used when a caller process dies or a request times out.

  Returns `{:ok, new_state}` if the request was found and removed,
  or `{:error, :not_found}` if the request ID doesn't exist.
  """
  @spec remove(state(), String.t()) :: {:ok, state()} | {:error, :not_found}
  def remove(state, id) do
    case Map.pop(state.pending_requests, id) do
      {%{monitor_ref: ref}, remaining} ->
        # Demonitor the caller
        Process.demonitor(ref, [:flush])
        {:ok, %{state | pending_requests: remaining}}

      {nil, _pending} ->
        {:error, :not_found}
    end
  end

  @doc """
  Cleans up stale pending requests that have exceeded the timeout.

  Returns `{removed_count, new_state}` with the number of removed requests.
  """
  @spec cleanup_stale(state(), non_neg_integer()) :: {non_neg_integer(), state()}
  def cleanup_stale(state, timeout_ms) do
    now = System.monotonic_time(:millisecond)

    {to_remove, remaining} =
      Enum.split_with(state.pending_requests, fn {_id, %{timestamp: ts}} ->
        now - ts > timeout_ms
      end)

    # Demonitor all removed requests
    Enum.each(to_remove, fn {_id, %{monitor_ref: ref}} ->
      Process.demonitor(ref, [:flush])
    end)

    removed_count = length(to_remove)
    {removed_count, %{state | pending_requests: Map.new(remaining)}}
  end

  @doc """
  Checks if a request ID is pending.
  """
  @spec pending?(state(), String.t()) :: boolean()
  def pending?(state, id) do
    Map.has_key?(state.pending_requests, id)
  end

  @doc """
  Lists all pending request IDs.
  """
  @spec list_pending(state()) :: [String.t()]
  def list_pending(state) do
    Map.keys(state.pending_requests)
  end
end
