defmodule CodePuppyControl.RuntimeState do
  @moduledoc """
  Runtime state management for Code Puppy.

  This module contains mutable runtime state that changes during execution.
  It is separate from the immutable configuration which is loaded from
  persistent storage at startup and should not be mutated at runtime.

  ## Runtime State vs Config

  - **Runtime state**: In-memory only, changes during execution, per-process/session
  - **Config**: Loaded from puppy.cfg, persistent across sessions, immutable at runtime

  ## State Managed

  - **Autosave session ID**: Runtime-only session identifier (per-process)
  - **Session model name**: Session-local model name cached after first read from config
  - **Session start time**: When the current session began
  - **Ephemeral caches**: System prompt, tool defs, context overhead, model name, etc.

  This is a global singleton GenServer named `CodePuppyControl.RuntimeState`.

  ## Parity with Python runtime_state.py

  The public API mirrors `code_puppy/runtime_state.py`, routing all operations
  through this GenServer. Cache invalidation methods were ported from Python's
  `AgentRuntimeState` (code_puppy/agents/agent_state.py) and are accessible
  both locally and via the stdio transport.
  """

  use GenServer

  require Logger

  defstruct [
    # Existing fields
    :autosave_id,
    :session_model,
    :session_start_time,

    # Caching fields from Python AgentRuntimeState
    :cached_system_prompt,
    :cached_tool_defs,
    :model_name_cache,
    :tool_ids_cache,
    :cached_context_overhead,
    :resolved_model_components_cache,

    # Keyword defaults (must come last in defstruct)
    delayed_compaction_requested: false
  ]

  @type t :: %__MODULE__{
          autosave_id: String.t() | nil,
          session_model: String.t() | nil,
          session_start_time: DateTime.t(),
          cached_system_prompt: String.t() | nil,
          cached_tool_defs: list(map()) | nil,
          model_name_cache: String.t() | nil,
          delayed_compaction_requested: boolean(),
          tool_ids_cache: any(),
          cached_context_overhead: integer() | nil,
          resolved_model_components_cache: map() | nil
        }

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the RuntimeState GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Gets or creates the current autosave session ID for this process.

  This is runtime-only state - it is not persisted to config and is
  unique to each process/session. The ID is lazily initialized with
  a timestamp when first accessed.
  """
  @spec get_current_autosave_id() :: String.t()
  def get_current_autosave_id do
    GenServer.call(__MODULE__, :get_current_autosave_id)
  end

  @doc """
  Force a new autosave session ID and return it.

  This creates a fresh session ID, effectively starting a new session
  while keeping the same process running.
  """
  @spec rotate_autosave_id() :: String.t()
  def rotate_autosave_id do
    GenServer.call(__MODULE__, :rotate_autosave_id)
  end

  @doc """
  Return the full session name used for autosaves (no file extension).
  """
  @spec get_current_autosave_session_name() :: String.t()
  def get_current_autosave_session_name do
    "auto_session_#{get_current_autosave_id()}"
  end

  @doc """
  Set the current autosave ID based on a full session name.

  Accepts names like 'auto_session_YYYYMMDD_HHMMSS' and extracts the ID part.
  Returns the ID that was set.
  """
  @spec set_current_autosave_from_session_name(String.t()) :: String.t()
  def set_current_autosave_from_session_name(session_name) do
    GenServer.call(__MODULE__, {:set_autosave_from_session_name, session_name})
  end

  @doc """
  Reset the autosave ID to nil.

  This is primarily for testing purposes. In normal operation, the autosave
  ID is set once and only changes via rotate_autosave_id/0.
  """
  @spec reset_autosave_id() :: :ok
  def reset_autosave_id do
    GenServer.cast(__MODULE__, :reset_autosave_id)
  end

  @doc """
  Get the cached session model name.

  Returns the cached model name, or nil if not yet initialized.
  """
  @spec get_session_model() :: String.t() | nil
  def get_session_model do
    GenServer.call(__MODULE__, :get_session_model)
  end

  @doc """
  Set the session-local model name.

  This updates only the runtime cache. To persist the model to config,
  use the config module which calls this internally after writing to
  the config file.
  """
  @spec set_session_model(String.t() | nil) :: :ok
  def set_session_model(model) do
    GenServer.cast(__MODULE__, {:set_session_model, model})
  end

  @doc """
  Reset the session-local model cache.

  This is primarily for testing purposes. In normal operation, the session
  model is set once at startup and only changes via set_session_model/1.
  """
  @spec reset_session_model() :: :ok
  def reset_session_model do
    GenServer.cast(__MODULE__, :reset_session_model)
  end

  @doc """
  Returns the current state for introspection.
  """
  @spec get_state() :: t()
  def get_state do
    GenServer.call(__MODULE__, :get_state)
  end

  # ============================================================================
  # Cache Invalidation Methods (from Python AgentRuntimeState)
  # ============================================================================

  @doc """
  Invalidate ephemeral caches. Call when model/tool config changes.

  Clears context overhead and tool ID caches. For a full reset
  including session-scoped caches, use `invalidate_all_token_caches/0`.
  """
  @spec invalidate_caches() :: :ok
  def invalidate_caches do
    GenServer.call(__MODULE__, :invalidate_caches)
  end

  @doc """
  Invalidate ALL token-related caches as a group.

  Must be called when any of these change:
  - System prompt (custom prompts, /prompts command)
  - Tool definitions (agent reload, MCP changes)
  - Model (model switch)
  - Puppy rules file (AGENTS.md changes)

  This prevents stale token estimates from causing incorrect
  context budgeting or premature/missed compaction.
  """
  @spec invalidate_all_token_caches() :: :ok
  def invalidate_all_token_caches do
    GenServer.call(__MODULE__, :invalidate_all_token_caches)
  end

  @doc """
  Invalidate cached system prompt when plugin state changes.

  This is called by plugins (e.g., prompt_store) when the user
  changes custom prompt instructions, ensuring the next agent
  invocation picks up the new prompt.

  Also invalidates context overhead since the system prompt
  contributes to overhead estimation.
  """
  @spec invalidate_system_prompt_cache() :: :ok
  def invalidate_system_prompt_cache do
    GenServer.call(__MODULE__, :invalidate_system_prompt_cache)
  end

  @doc """
  Persist the current autosave snapshot and rotate to a fresh session.

  This is best-effort and never raises: autosave rotation is not a
  critical-path operation, so any failure (disk full, etc.) falls back
  to a timestamp-based ID so the caller can keep running.

  Returns the new autosave session ID.

  ## Parity

  Mirrors `code_puppy/runtime_state.py:finalize_autosave_session()`.
  The Python version also calls `auto_save_session_if_enabled()` before
  rotating; the Elixir version accepts an optional `save_fn` callback
  (default: `&auto_save_if_enabled/0`) so callers can inject the
  save behaviour or skip it entirely.
  """
  @spec finalize_autosave_session() :: String.t()
  def finalize_autosave_session do
    finalize_autosave_session(&auto_save_if_enabled/0)
  end

  @doc """
  Same as `finalize_autosave_session/0` but with an injectable save callback.

  The `save_fn` is invoked before the rotation. If it raises, the error
  is logged and rotation continues. The default callback delegates to
  `auto_save_if_enabled/0`.
  """
  @spec finalize_autosave_session((-> :ok | {:ok, any()} | any())) :: String.t()
  def finalize_autosave_session(save_fn) do
    # Step 1: Try to save the current session (best-effort)
    try do
      save_fn.()
    rescue
      exc ->
        Logger.warning("auto_save callback failed during finalize: #{inspect(exc)}")
    end

    # Step 2: Rotate to a new autosave ID (best-effort)
    try do
      rotate_autosave_id()
    rescue
      exc ->
        Logger.warning(
          "rotate_autosave_id failed during finalize; using timestamp fallback: #{inspect(exc)}"
        )

        generate_fallback_id()
    end
  end

  @doc """
  Reset all state to initial values (primarily for testing).
  """
  @spec reset_for_test() :: :ok
  def reset_for_test do
    GenServer.call(__MODULE__, :reset_for_test)
  end

  # ============================================================================
  # Cache Getter / Setter API
  #
  # These provide GenServer-mediated access to the ephemeral cache fields.
  # They mirror the per-instance cache properties on Python's AgentRuntimeState
  # but are stored globally in this singleton GenServer.
  # ============================================================================

  @doc """
  Get the cached system prompt string, or nil if not yet computed.
  """
  @spec get_cached_system_prompt() :: String.t() | nil
  def get_cached_system_prompt do
    GenServer.call(__MODULE__, :get_cached_system_prompt)
  end

  @doc """
  Set the cached system prompt string.
  """
  @spec set_cached_system_prompt(String.t() | nil) :: :ok
  def set_cached_system_prompt(prompt) do
    GenServer.cast(__MODULE__, {:set_cached_system_prompt, prompt})
  end

  @doc """
  Get the cached tool definitions list, or nil if not yet computed.
  """
  @spec get_cached_tool_defs() :: list(map()) | nil
  def get_cached_tool_defs do
    GenServer.call(__MODULE__, :get_cached_tool_defs)
  end

  @doc """
  Set the cached tool definitions list.
  """
  @spec set_cached_tool_defs(list(map()) | nil) :: :ok
  def set_cached_tool_defs(defs) do
    GenServer.cast(__MODULE__, {:set_cached_tool_defs, defs})
  end

  @doc """
  Get the cached model name, or nil if not yet resolved.
  """
  @spec get_model_name_cache() :: String.t() | nil
  def get_model_name_cache do
    GenServer.call(__MODULE__, :get_model_name_cache)
  end

  @doc """
  Set the cached model name.
  """
  @spec set_model_name_cache(String.t() | nil) :: :ok
  def set_model_name_cache(name) do
    GenServer.cast(__MODULE__, {:set_model_name_cache, name})
  end

  @doc """
  Get whether delayed compaction has been requested.
  """
  @spec get_delayed_compaction_requested() :: boolean()
  def get_delayed_compaction_requested do
    GenServer.call(__MODULE__, :get_delayed_compaction_requested)
  end

  @doc """
  Set the delayed compaction requested flag.
  """
  @spec set_delayed_compaction_requested(boolean()) :: :ok
  def set_delayed_compaction_requested(value) do
    GenServer.cast(__MODULE__, {:set_delayed_compaction_requested, value})
  end

  @doc """
  Get the per-invocation tool IDs cache.
  """
  @spec get_tool_ids_cache() :: any()
  def get_tool_ids_cache do
    GenServer.call(__MODULE__, :get_tool_ids_cache)
  end

  @doc """
  Set the per-invocation tool IDs cache.
  """
  @spec set_tool_ids_cache(any()) :: :ok
  def set_tool_ids_cache(cache) do
    GenServer.cast(__MODULE__, {:set_tool_ids_cache, cache})
  end

  @doc """
  Get the cached context overhead estimate, or nil if not yet computed.
  """
  @spec get_cached_context_overhead() :: integer() | nil
  def get_cached_context_overhead do
    GenServer.call(__MODULE__, :get_cached_context_overhead)
  end

  @doc """
  Set the cached context overhead estimate.
  """
  @spec set_cached_context_overhead(integer() | nil) :: :ok
  def set_cached_context_overhead(value) do
    GenServer.cast(__MODULE__, {:set_cached_context_overhead, value})
  end

  @doc """
  Get the resolved model components cache map, or nil if not yet computed.
  """
  @spec get_resolved_model_components_cache() :: map() | nil
  def get_resolved_model_components_cache do
    GenServer.call(__MODULE__, :get_resolved_model_components_cache)
  end

  @doc """
  Set the resolved model components cache map.
  """
  @spec set_resolved_model_components_cache(map() | nil) :: :ok
  def set_resolved_model_components_cache(cache) do
    GenServer.cast(__MODULE__, {:set_resolved_model_components_cache, cache})
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    state = %__MODULE__{
      autosave_id: nil,
      session_model: nil,
      session_start_time: DateTime.utc_now(),
      cached_system_prompt: nil,
      cached_tool_defs: nil,
      model_name_cache: nil,
      delayed_compaction_requested: false,
      tool_ids_cache: nil,
      cached_context_overhead: nil,
      resolved_model_components_cache: nil
    }

    Logger.info("RuntimeState initialized")
    {:ok, state}
  end

  @impl true
  def handle_call(:get_current_autosave_id, _from, %{autosave_id: nil} = state) do
    new_id = generate_autosave_id()
    new_state = %{state | autosave_id: new_id}
    {:reply, new_id, new_state}
  end

  def handle_call(:get_current_autosave_id, _from, state) do
    {:reply, state.autosave_id, state}
  end

  @impl true
  def handle_call(:rotate_autosave_id, _from, state) do
    new_id = generate_autosave_id()
    new_state = %{state | autosave_id: new_id}
    Logger.info("Rotated autosave session ID to #{new_id}")
    {:reply, new_id, new_state}
  end

  @impl true
  def handle_call({:set_autosave_from_session_name, session_name}, _from, state) do
    prefix = "auto_session_"

    new_id =
      if String.starts_with?(session_name, prefix) do
        String.replace_prefix(session_name, prefix, "")
      else
        session_name
      end

    new_state = %{state | autosave_id: new_id}
    {:reply, new_id, new_state}
  end

  @impl true
  def handle_call(:get_session_model, _from, state) do
    {:reply, state.session_model, state}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, state}
  end

  @impl true
  def handle_call(:invalidate_caches, _from, state) do
    {:reply, :ok, %{state | cached_context_overhead: nil, tool_ids_cache: nil}}
  end

  @impl true
  def handle_call(:invalidate_all_token_caches, _from, state) do
    {:reply, :ok,
     %{
       state
       | cached_context_overhead: nil,
         cached_system_prompt: nil,
         cached_tool_defs: nil,
         tool_ids_cache: nil,
         resolved_model_components_cache: nil
     }}
  end

  @impl true
  def handle_call(:invalidate_system_prompt_cache, _from, state) do
    {:reply, :ok, %{state | cached_system_prompt: nil, cached_context_overhead: nil}}
  end

  @impl true
  def handle_call(:reset_for_test, _from, _state) do
    {:reply, :ok,
     %__MODULE__{
       autosave_id: nil,
       session_model: nil,
       session_start_time: DateTime.utc_now(),
       cached_system_prompt: nil,
       cached_tool_defs: nil,
       model_name_cache: nil,
       delayed_compaction_requested: false,
       tool_ids_cache: nil,
       cached_context_overhead: nil,
       resolved_model_components_cache: nil
     }}
  end

  # ---------------------------------------------------------------------------
  # Cache getter calls
  # ---------------------------------------------------------------------------

  @impl true
  def handle_call(:get_cached_system_prompt, _from, state) do
    {:reply, state.cached_system_prompt, state}
  end

  @impl true
  def handle_call(:get_cached_tool_defs, _from, state) do
    {:reply, state.cached_tool_defs, state}
  end

  @impl true
  def handle_call(:get_model_name_cache, _from, state) do
    {:reply, state.model_name_cache, state}
  end

  @impl true
  def handle_call(:get_delayed_compaction_requested, _from, state) do
    {:reply, state.delayed_compaction_requested, state}
  end

  @impl true
  def handle_call(:get_tool_ids_cache, _from, state) do
    {:reply, state.tool_ids_cache, state}
  end

  @impl true
  def handle_call(:get_cached_context_overhead, _from, state) do
    {:reply, state.cached_context_overhead, state}
  end

  @impl true
  def handle_call(:get_resolved_model_components_cache, _from, state) do
    {:reply, state.resolved_model_components_cache, state}
  end

  # ---------------------------------------------------------------------------
  # Casts
  # ---------------------------------------------------------------------------

  @impl true
  def handle_cast(:reset_autosave_id, state) do
    {:noreply, %{state | autosave_id: nil}}
  end

  @impl true
  def handle_cast({:set_session_model, model}, state) do
    {:noreply, %{state | session_model: model}}
  end

  @impl true
  def handle_cast(:reset_session_model, state) do
    {:noreply, %{state | session_model: nil}}
  end

  # ---------------------------------------------------------------------------
  # Cache setter casts
  # ---------------------------------------------------------------------------

  @impl true
  def handle_cast({:set_cached_system_prompt, prompt}, state) do
    {:noreply, %{state | cached_system_prompt: prompt}}
  end

  @impl true
  def handle_cast({:set_cached_tool_defs, defs}, state) do
    {:noreply, %{state | cached_tool_defs: defs}}
  end

  @impl true
  def handle_cast({:set_model_name_cache, name}, state) do
    {:noreply, %{state | model_name_cache: name}}
  end

  @impl true
  def handle_cast({:set_delayed_compaction_requested, value}, state) do
    {:noreply, %{state | delayed_compaction_requested: value}}
  end

  @impl true
  def handle_cast({:set_tool_ids_cache, cache}, state) do
    {:noreply, %{state | tool_ids_cache: cache}}
  end

  @impl true
  def handle_cast({:set_cached_context_overhead, value}, state) do
    {:noreply, %{state | cached_context_overhead: value}}
  end

  @impl true
  def handle_cast({:set_resolved_model_components_cache, cache}, state) do
    {:noreply, %{state | resolved_model_components_cache: cache}}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("RuntimeState received unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp generate_autosave_id do
    # Use a full timestamp so tests and UX can predict the name if needed
    DateTime.utc_now()
    |> Calendar.strftime("%Y%m%d_%H%M%S")
  end

  # Fallback ID when rotate_autosave_id fails during finalize.
  # Matches Python's fallback format: `%Y%m%d_%H%M%S_fallback`
  defp generate_fallback_id do
    DateTime.utc_now()
    |> Calendar.strftime("%Y%m%d_%H%M%S") |> Kernel.<>("_fallback")
  end

  # Best-effort auto-save: persists current session if the config flag is on.
  # Returns `:ok` regardless of outcome (mirrors Python's never-raises contract).
  defp auto_save_if_enabled do
    if CodePuppyControl.Config.TUI.auto_save_session?() do
      # TODO(code_puppy-ctj.4): Wire into agent state to fetch message history
      # and call SessionStorage.save_session_async/3 once the agent loop
      # integration is complete. For now, log and return — the rotate still
      # happens in finalize_autosave_session.
      Logger.debug("RuntimeState: auto_save_if_enabled skipped (no agent history access yet)")
    end

    :ok
  end
end
