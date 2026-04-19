defmodule CodePuppyControl.PtyManager.Stub do
  @moduledoc """
  Stub PTY manager for development and testing.

  Records calls in an Agent so tests can assert on what was sent.
  Does NOT spawn an actual OS PTY — that is the job of the real
  implementation (bd-217).

  ## Usage in tests

      # Configure the stub (already default in test env)
      Application.put_env(:code_puppy_control, :pty_manager, __MODULE__)

      # Inspect recorded calls
      calls = CodePuppyControl.PtyManager.Stub.get_calls("my-session")

  ## Usage in dev

  The stub is the default when no real PTY manager is configured.
  It accepts all calls and returns success tuples, but the
  `:on_output` callback is never invoked (no PTY output).
  """

  @behaviour CodePuppyControl.PtyManager

  use Agent

  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    Agent.start_link(fn -> %{} end, name: name)
  end

  # ===========================================================================
  # Test helpers
  # ===========================================================================

  @doc "Get all recorded calls for a session (returns a list of `{action, payload}` tuples)."
  @spec get_calls(String.t()) :: [{atom(), term()}]
  def get_calls(session_id) do
    Agent.get(agent_name(), fn state ->
      Map.get(state, {:calls, session_id}, [])
    end)
  end

  @doc "Clear all recorded calls."
  @spec clear_all() :: :ok
  def clear_all do
    Agent.update(agent_name(), fn _state -> %{} end)
  end

  @doc "Simulate PTY output for a session (fires the `:on_output` callback)."
  @spec simulate_output(String.t(), binary()) :: :ok
  def simulate_output(session_id, data) do
    Agent.get(agent_name(), fn state ->
      case Map.get(state, {:on_output, session_id}) do
        nil -> :ok
        callback -> callback.(data)
      end

      :ok
    end)
  end

  @doc """
  Set a custom PTY session ID to return from `create_session/2`.

  When set, `create_session("topic-id", ...)` returns `%{id: custom_id, ...}`
  and records calls under `custom_id` for write/resize/close. This lets
  tests verify that the channel uses the PTY-assigned ID (not the topic ID).

  Pass `nil` to reset to default behaviour (PTY ID == topic ID).
  """
  @spec set_custom_pty_id(String.t() | nil) :: :ok
  def set_custom_pty_id(custom_id) do
    Agent.update(agent_name(), fn state ->
      if custom_id do
        Map.put(state, :custom_pty_id, custom_id)
      else
        Map.delete(state, :custom_pty_id)
      end
    end)
  end

  # ===========================================================================
  # PtyManager callback implementations
  # ===========================================================================

  @impl true
  def create_session(session_id, opts) do
    on_output = Keyword.get(opts, :on_output)
    cols = Keyword.get(opts, :cols, 80)
    rows = Keyword.get(opts, :rows, 24)

    # Allow tests to override the returned PTY ID
    pty_id =
      Agent.get(agent_name(), fn state ->
        Map.get(state, :custom_pty_id, session_id)
      end)

    Agent.update(agent_name(), fn state ->
      state
      |> Map.put({:session, pty_id}, %{id: pty_id, cols: cols, rows: rows})
      |> Map.put({:on_output, pty_id}, on_output)
      |> Map.update({:calls, pty_id}, [{:create, %{cols: cols, rows: rows}}], fn calls ->
        calls ++ [{:create, %{cols: cols, rows: rows}}]
      end)
    end)

    {:ok, %{id: pty_id, cols: cols, rows: rows}}
  end

  @impl true
  def write(session_id, data) do
    Agent.update(agent_name(), fn state ->
      Map.update(state, {:calls, session_id}, [{:write, data}], fn calls ->
        calls ++ [{:write, data}]
      end)
    end)

    :ok
  end

  @impl true
  def resize(session_id, cols, rows) do
    Agent.update(agent_name(), fn state ->
      state
      |> Map.update({:session, session_id}, %{cols: cols, rows: rows}, fn session ->
        %{session | cols: cols, rows: rows}
      end)
      |> Map.update({:calls, session_id}, [{:resize, %{cols: cols, rows: rows}}], fn calls ->
        calls ++ [{:resize, %{cols: cols, rows: rows}}]
      end)
    end)

    :ok
  end

  @impl true
  def close_session(session_id) do
    Agent.update(agent_name(), fn state ->
      state
      |> Map.delete({:session, session_id})
      |> Map.delete({:on_output, session_id})
      |> Map.update({:calls, session_id}, [{:close, nil}], fn calls ->
        calls ++ [{:close, nil}]
      end)
    end)

    :ok
  end

  @impl true
  def get_session(session_id) do
    case Agent.get(agent_name(), fn state -> Map.get(state, {:session, session_id}) end) do
      nil -> {:error, :not_found}
      session -> {:ok, session}
    end
  end

  @impl true
  def list_sessions do
    Agent.get(agent_name(), fn state ->
      state
      |> Map.keys()
      |> Enum.filter(fn
        {:session, _id} -> true
        _ -> false
      end)
      |> Enum.map(fn {:session, id} -> id end)
    end)
  end

  # ===========================================================================
  # Private
  # ===========================================================================

  defp agent_name, do: __MODULE__
end
