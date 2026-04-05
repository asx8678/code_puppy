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
          type: atom()
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

  ## Examples

      iex> state = %{pending_requests: %{}, request_counter: 0, listeners: MapSet.new()}
      iex> from = {self(), :erlang.make_ref()}
      iex> Mana.MessageBus.RequestTracker.track(state, "req_123", from, :input)
      %{pending_requests: %{"req_123" => %{from: from, type: :input}}, request_counter: 0, listeners: MapSet.new()}
  """
  @spec track(state(), String.t(), GenServer.from(), atom()) :: state()
  def track(state, id, from, type) do
    pending = Map.put(state.pending_requests, id, %{from: from, type: type})

    %{state | pending_requests: pending}
  end

  @doc """
  Resolves a pending request with a response.

  Returns `{:ok, new_state}` if the request was found and resolved,
  or `{:error, :not_found}` if the request ID doesn't exist.

  ## Examples

      iex> from = {self(), :erlang.make_ref()}
      iex> state = %{pending_requests: %{"req_123" => %{from: from, type: :input}}, request_counter: 0, listeners: MapSet.new()}
      iex> Mana.MessageBus.RequestTracker.resolve(state, "req_123", "user response")
      {:ok, %{pending_requests: %{}, request_counter: 0, listeners: MapSet.new()}}
  """
  @spec resolve(state(), String.t(), any()) :: {:ok, state()} | {:error, :not_found}
  def resolve(state, id, response) do
    case Map.pop(state.pending_requests, id) do
      {%{from: from, type: _type}, remaining} ->
        # Reply to the waiting process
        GenServer.reply(from, {:ok, response})
        {:ok, %{state | pending_requests: remaining}}

      {nil, _pending} ->
        {:error, :not_found}
    end
  end

  @doc """
  Checks if a request ID is pending.

  ## Examples

      iex> state = %{pending_requests: %{"req_123" => %{from: nil, type: :input}}, request_counter: 0, listeners: MapSet.new()}
      iex> Mana.MessageBus.RequestTracker.pending?(state, "req_123")
      true
      iex> Mana.MessageBus.RequestTracker.pending?(state, "req_456")
      false
  """
  @spec pending?(state(), String.t()) :: boolean()
  def pending?(state, id) do
    Map.has_key?(state.pending_requests, id)
  end

  @doc """
  Lists all pending request IDs.

  ## Examples

      iex> state = %{pending_requests: %{"req_123" => %{}, "req_456" => %{}}, request_counter: 0, listeners: MapSet.new()}
      iex> Mana.MessageBus.RequestTracker.list_pending(state)
      ["req_123", "req_456"]
  """
  @spec list_pending(state()) :: [String.t()]
  def list_pending(state) do
    Map.keys(state.pending_requests)
  end
end
