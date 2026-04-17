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

  This is a global singleton GenServer named `CodePuppyControl.RuntimeState`.
  """

  use GenServer

  require Logger

  defstruct [
    :autosave_id,
    :session_model,
    :session_start_time
  ]

  @type t :: %__MODULE__{
          autosave_id: String.t() | nil,
          session_model: String.t() | nil,
          session_start_time: DateTime.t()
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
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    state = %__MODULE__{
      autosave_id: nil,
      session_model: nil,
      session_start_time: DateTime.utc_now()
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
end
