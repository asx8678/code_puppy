defmodule Mana.OAuth.RefreshManager do
  @moduledoc """
  Serialized token refresh manager for OAuth providers.

  This GenServer prevents race conditions when multiple requests simultaneously
  encounter 401 Unauthorized responses. Instead of each request triggering
  its own token refresh, this manager:

  1. Serializes refresh attempts - only one refresh happens at a time per provider
  2. Queues waiting requests during an in-progress refresh
  3. Shares the refresh result with all queued requests
  4. Tracks refresh state with `:idle`, `:refreshing`, and `:cooldown` states

  ## Usage

      # Refresh token if needed (will block and wait if refresh in progress)
      {:ok, tokens} = Mana.OAuth.RefreshManager.refresh_if_needed("chatgpt", fn tokens ->
        # Your refresh logic here
        {:ok, %{"access_token" => "new_token", "expires_at" => 1234567890}}
      end)

      # Or use the lower-level API directly
      {:ok, tokens} = Mana.OAuth.RefreshManager.execute_refresh("chatgpt", refresh_fn)

  ## Race Condition Prevention

  When multiple processes call `refresh_if_needed/2` simultaneously:

  1. First caller triggers the actual HTTP refresh request
  2. Subsequent callers are queued and wait for the result
  3. All callers receive the same result (success or failure)
  4. This prevents multiple concurrent refresh token uses, which can
     cause some providers to invalidate the refresh token
  """

  use GenServer

  require Logger

  alias Mana.OAuth.TokenStore

  # Refresh state tracking
  defstruct refresh_state: %{}, pending: %{}

  # State machine for refresh status
  @state_idle :idle
  @state_refreshing :refreshing
  @state_cooldown :cooldown

  # Cooldown period after successful refresh (milliseconds)
  @cooldown_ms 100

  @doc """
  Start the RefreshManager GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Initialize the GenServer with empty state.
  """
  @impl true
  def init(_opts) do
    state = %__MODULE__{
      refresh_state: %{},
      pending: %{}
    }

    {:ok, state}
  end

  @doc """
  Child specification for supervisor integration.
  """
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :permanent
    }
  end

  @doc """
  Check if token needs refresh and execute refresh with serialization.

  This is the main API for token refresh. It checks if the token is expired,
  and if so, executes a serialized refresh. Multiple concurrent calls will
  be coalesced into a single refresh operation.

  ## Parameters

  - `provider` - The provider identifier (e.g., "chatgpt", "claude_code")
  - `refresh_fn` - Function that performs the actual refresh. Should accept
    current tokens and return `{:ok, new_tokens}` or `{:error, reason}`

  ## Returns

  - `{:ok, tokens}` - Valid (possibly refreshed) tokens
  - `{:error, reason}` - Failed to get or refresh tokens

  ## Examples

      {:ok, tokens} = Mana.OAuth.RefreshManager.refresh_if_needed("chatgpt", fn tokens ->
        Mana.OAuth.ChatGPT.refresh_token(tokens)
      end)
  """
  @spec refresh_if_needed(String.t(), (map() -> {:ok, map()} | {:error, term()})) ::
          {:ok, map()} | {:error, term()}
  def refresh_if_needed(provider, refresh_fn) do
    case TokenStore.load(provider) do
      {:ok, tokens} ->
        if TokenStore.expired?(tokens) do
          execute_refresh(provider, refresh_fn)
        else
          {:ok, tokens}
        end

      error ->
        error
    end
  end

  @doc """
  Execute a serialized token refresh for a provider.

  This function ensures that only one refresh operation is in flight at a time
  for each provider. If a refresh is already in progress, the caller will wait
  for it to complete and receive the same result.

  ## Parameters

  - `provider` - The provider identifier
  - `refresh_fn` - Function that performs the actual refresh

  ## Returns

  - `{:ok, tokens}` - Successfully refreshed tokens
  - `{:error, reason}` - Refresh failed
  """
  @spec execute_refresh(String.t(), (map() -> {:ok, map()} | {:error, term()})) ::
          {:ok, map()} | {:error, term()}
  def execute_refresh(provider, refresh_fn) do
    GenServer.call(__MODULE__, {:refresh, provider, refresh_fn}, :infinity)
  end

  @doc """
  Reset the refresh state for a provider.

  This is primarily used for testing to ensure clean state between tests.
  Clears any pending refresh state for the given provider.

  ## Parameters

  - `provider` - The provider identifier to reset
  """
  @spec reset_provider(String.t()) :: :ok
  def reset_provider(provider) do
    GenServer.call(__MODULE__, {:reset_provider, provider})
  end

  # ============================================================================
  # GenServer Callbacks
  # ============================================================================

  @impl true
  def handle_call({:refresh, provider, refresh_fn}, from, state) do
    current_state = Map.get(state.refresh_state, provider, @state_idle)

    case current_state do
      @state_idle ->
        # No refresh in progress, start one
        Logger.debug("Starting token refresh for provider '#{provider}'")
        new_state = start_refresh(state, provider, refresh_fn, from)
        {:noreply, new_state}

      @state_refreshing ->
        # Refresh in progress, queue this caller
        Logger.debug("Queueing token refresh request for provider '#{provider}'")
        new_state = queue_caller(state, provider, from)
        {:noreply, new_state}

      @state_cooldown ->
        # Just finished a refresh, check if token is now valid
        # If still expired (rare edge case), start a new refresh
        handle_cooldown_state(state, provider, refresh_fn, from)
    end
  end

  @impl true
  def handle_call({:reset_provider, provider}, _from, state) do
    # Clear the refresh state and pending queue for this provider
    new_refresh_state = Map.delete(state.refresh_state, provider)
    new_pending = Map.delete(state.pending, provider)
    {:reply, :ok, %{state | refresh_state: new_refresh_state, pending: new_pending}}
  end

  @impl true
  def handle_info({:refresh_complete, provider, result}, state) do
    {replies, new_state} = complete_refresh(state, provider, result)

    # Send replies to all waiting callers
    Enum.each(replies, fn {to, reply} ->
      GenServer.reply(to, reply)
    end)

    {:noreply, new_state}
  end

  @impl true
  def handle_info({:cooldown_end, provider}, state) do
    new_refresh_state = Map.put(state.refresh_state, provider, @state_idle)
    {:noreply, %{state | refresh_state: new_refresh_state}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.warning("[#{__MODULE__}] Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  # Handle the cooldown state in handle_call - extracted to reduce nesting
  defp handle_cooldown_state(state, provider, refresh_fn, from) do
    case TokenStore.load(provider) do
      {:ok, tokens} ->
        if TokenStore.expired?(tokens) do
          Logger.debug("Token still expired after cooldown, refreshing again for '#{provider}'")
          new_state = start_refresh(state, provider, refresh_fn, from)
          {:noreply, new_state}
        else
          # Token is valid, reply immediately
          {:reply, {:ok, tokens}, state}
        end

      error ->
        {:reply, error, state}
    end
  end

  defp start_refresh(state, provider, refresh_fn, initial_caller) do
    # Set state to refreshing
    new_refresh_state = Map.put(state.refresh_state, provider, @state_refreshing)

    # Queue the initial caller
    new_pending = Map.put(state.pending, provider, [initial_caller])

    new_state = %{state | refresh_state: new_refresh_state, pending: new_pending}

    # Spawn the actual refresh work with monitoring
    pid = self()

    Task.Supervisor.start_child(Mana.TaskSupervisor, fn ->
      result =
        try do
          perform_refresh(provider, refresh_fn)
        catch
          kind, reason ->
            require Logger
            Logger.error("Token refresh crashed for '#{provider}': #{kind} - #{inspect(reason)}")
            {:error, {:refresh_crashed, kind, reason}}
        end

      send(pid, {:refresh_complete, provider, result})
    end)

    new_state
  end

  defp queue_caller(state, provider, from) do
    current_queue = Map.get(state.pending, provider, [])
    new_queue = current_queue ++ [from]
    %{state | pending: Map.put(state.pending, provider, new_queue)}
  end

  defp perform_refresh(provider, refresh_fn) do
    Logger.info("Executing token refresh for provider '#{provider}'")

    case TokenStore.load(provider) do
      {:ok, tokens} ->
        do_refresh_call(tokens, provider, refresh_fn)

      error ->
        Logger.error("Failed to load tokens for refresh (#{provider}): #{inspect(error)}")
        error
    end
  end

  defp do_refresh_call(tokens, provider, refresh_fn) do
    case refresh_fn.(tokens) do
      {:ok, new_tokens} ->
        # Save the new tokens
        case TokenStore.save(provider, new_tokens) do
          :ok ->
            Logger.info("Successfully refreshed token for provider '#{provider}'")
            {:ok, new_tokens}

          {:error, reason} ->
            Logger.warning("Failed to save refreshed tokens for '#{provider}': #{inspect(reason)}")
            # Still return the new tokens even if saving failed
            {:ok, new_tokens}
        end

      {:error, reason} = error ->
        Logger.error("Token refresh failed for '#{provider}': #{inspect(reason)}")
        error
    end
  end

  defp complete_refresh(state, provider, result) do
    # Get all callers waiting for this refresh
    callers = Map.get(state.pending, provider, [])

    # Create reply tuples for each caller
    replies = Enum.map(callers, fn from -> {from, result} end)

    # Clear the pending queue for this provider
    new_pending = Map.delete(state.pending, provider)

    # Set state to cooldown (prevents immediate re-refresh)
    new_refresh_state = Map.put(state.refresh_state, provider, @state_cooldown)

    # Schedule cooldown end
    Process.send_after(self(), {:cooldown_end, provider}, @cooldown_ms)

    new_state = %{state | refresh_state: new_refresh_state, pending: new_pending}

    {replies, new_state}
  end
end
