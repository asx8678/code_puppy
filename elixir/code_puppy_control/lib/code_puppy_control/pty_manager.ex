defmodule CodePuppyControl.PtyManager do
  @moduledoc """
  Behaviour contract for PTY session management.

  Defines the interface that terminal channel consumers rely on.
  The real implementation lives in a separate module (bd-217) that
  wraps OS-level PTY via `Port.open/2` or `erlexec`.

  A stub implementation (`CodePuppyControl.PtyManager.Stub`) is provided
  for development and testing when the native PTY backend is unavailable.

  ## Callback lifecycle

      {:ok, session} = PtyManager.create_session("sess-1", opts)
      :ok           = PtyManager.write("sess-1", "ls\\n")
      :ok           = PtyManager.resize("sess-1", 120, 40)
      :ok           = PtyManager.close_session("sess-1")

  ## Event flow

  Output from the PTY process is delivered via the `:on_output` callback
  provided at session creation time. The callback receives raw binary data
  and is expected to push it to the channel/client without blocking the
  PTY reader loop.
  """

  @type session_id :: String.t()
  @type on_output :: (binary() -> :ok | {:error, term()})
  @type create_opts :: [
          cols: pos_integer(),
          rows: pos_integer(),
          shell: String.t(),
          on_output: on_output()
        ]

  @callback create_session(session_id(), create_opts()) ::
              {:ok, map()} | {:error, term()}

  @callback write(session_id(), binary()) :: :ok | {:error, term()}

  @callback resize(session_id(), pos_integer(), pos_integer()) :: :ok | {:error, term()}

  @callback close_session(session_id()) :: :ok | {:error, term()}

  @callback get_session(session_id()) :: {:ok, map()} | {:error, :not_found}

  @callback list_sessions() :: [session_id()]

  # ===========================================================================
  # Runtime dispatch — delegates to the configured implementation
  # ===========================================================================

  @doc """
  Returns the module that implements the `CodePuppyControl.PtyManager` behaviour.

  Configuration (in `config/config.exs` or runtime):

      config :code_puppy_control, :pty_manager, CodePuppyControl.PtyManager.Stub

  Falls back to `CodePuppyControl.PtyManager.Stub` when not configured.
  """
  @spec impl() :: module()
  def impl do
    Application.get_env(:code_puppy_control, :pty_manager, __MODULE__.Stub)
  end

  @doc "Create a new PTY session."
  @spec create_session(session_id(), create_opts()) :: {:ok, map()} | {:error, term()}
  def create_session(session_id, opts \\ []) do
    impl().create_session(session_id, opts)
  end

  @doc "Write data to a PTY session's stdin."
  @spec write(session_id(), binary()) :: :ok | {:error, term()}
  def write(session_id, data) do
    impl().write(session_id, data)
  end

  @doc "Resize a PTY session's terminal dimensions."
  @spec resize(session_id(), pos_integer(), pos_integer()) :: :ok | {:error, term()}
  def resize(session_id, cols, rows) do
    impl().resize(session_id, cols, rows)
  end

  @doc "Close and clean up a PTY session."
  @spec close_session(session_id()) :: :ok | {:error, term()}
  def close_session(session_id) do
    impl().close_session(session_id)
  end

  @doc "Get a session by ID."
  @spec get_session(session_id()) :: {:ok, map()} | {:error, :not_found}
  def get_session(session_id) do
    impl().get_session(session_id)
  end

  @doc "List all active session IDs."
  @spec list_sessions() :: [session_id()]
  def list_sessions do
    impl().list_sessions()
  end
end
