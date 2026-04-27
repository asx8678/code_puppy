defmodule CodePuppyControl.WorkflowState do
  @moduledoc """
  Backward-compatible facade for `CodePuppyControl.Workflow.State`.

  This module delegates all calls to the new `Workflow.State` module.
  New code should use `Workflow.State` directly.

  ## Migration

  | Old (deprecated)                | New                     |
  |----------------------------------|-------------------------|
  | `WorkflowState.set_flag/1`       | `Workflow.State.set_flag/1` |
  | `WorkflowState.has_flag?/1`      | `Workflow.State.has_flag?/1` |
  | `WorkflowState.reset/0`          | `Workflow.State.reset/0` |
  | `WorkflowState.put_metadata/2`    | `Workflow.State.put_metadata/2` |
  | `WorkflowState.get_metadata/2`    | `Workflow.State.get_metadata/2` |

  This module will be removed in a future release.
  """

  # TODO(code-puppy-ctj.3): Remove after all callers migrated to Workflow.State

  alias CodePuppyControl.Workflow.State

  # ── Child Spec (for custom supervision trees) ────────────────────────────

  # If this module is added to a supervision tree, it starts the underlying
  # Workflow.State agent. The application tree now starts Workflow.State
  # directly, so this is only needed for custom supervision trees.
  @doc false
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {State, :start_link, [Keyword.put_new(opts, :name, State)]},
      type: :worker,
      restart: :permanent,
      shutdown: 500
    }
  end

  # ── Delegated Flag Definitions ──────────────────────────────────────────

  @doc "Returns all known flag definitions as `[{atom, description}]`."
  @spec all_flags() :: [{atom(), String.t()}]
  def all_flags, do: State.all_flags()

  @doc "Returns all known flag name atoms."
  @spec flag_names() :: [atom()]
  def flag_names, do: State.flag_names()

  @doc "Checks whether `name` is a known flag atom."
  @spec known_flag?(atom()) :: boolean()
  def known_flag?(name), do: State.known_flag?(name)

  # ── State Struct ──────────────────────────────────────────────────────────

  # Struct retained for backward compat — callers may pattern-match on it.
  # Unlike the previous implementation which returned a %Workflow.State{}
  # (different struct type), new/0 now returns a proper %WorkflowState{}
  # struct with fields copied from Workflow.State.new/0.
  defstruct flags: MapSet.new(), metadata: %{}, start_time: nil

  @type t :: %__MODULE__{
          flags: MapSet.t(atom()),
          metadata: %{String.t() => any()},
          start_time: integer() | nil
        }

  @doc """
  Creates a fresh workflow state struct.

  Returns a `%WorkflowState{}` struct (not `%Workflow.State{}`) for
  backward compatibility with callers that pattern-match on the
  facade struct type.
  """
  @spec new() :: t()
  def new do
    internal = State.new()

    %__MODULE__{
      flags: internal.flags,
      metadata: internal.metadata,
      start_time: internal.start_time
    }
  end

  # ── Agent API ─────────────────────────────────────────────────────────────

  # ── Delegated Agent API ─────────────────────────────────────────────────

  @doc "Starts the WorkflowState agent (delegates to Workflow.State)."
  @spec start_link(keyword()) :: Agent.on_start()
  def start_link(opts \\ []), do: State.start_link(opts)

  @doc "Returns the current workflow state as a facade struct."
  @spec get() :: t()
  def get, do: to_facade(State.get())

  @doc "Resets to a fresh workflow state and returns it as a facade struct."
  @spec reset() :: t()
  def reset, do: to_facade(State.reset())

  @doc "Sets a flag (adds it to the active set). Unknown flags are ignored."
  @spec set_flag(atom()) :: :ok
  def set_flag(flag), do: State.set_flag(flag)

  @doc "Clears a flag (removes it from the active set). Unknown flags are ignored."
  @spec clear_flag(atom()) :: :ok
  def clear_flag(flag), do: State.clear_flag(flag)

  @doc "Checks whether a flag is active. Returns `false` for unknown flags."
  @spec has_flag?(atom()) :: boolean()
  def has_flag?(flag), do: State.has_flag?(flag)

  @doc "Stores a metadata key/value pair."
  @spec put_metadata(String.t(), any()) :: :ok
  def put_metadata(key, value), do: State.put_metadata(key, value)

  @doc "Reads a metadata value, defaulting to `default`."
  @spec get_metadata(String.t(), any()) :: any()
  def get_metadata(key, default \\ nil), do: State.get_metadata(key, default)

  @doc "Returns a map of current metadata."
  @spec metadata() :: %{String.t() => any()}
  def metadata, do: State.metadata()

  @doc "Returns the count of active flags."
  @spec active_count() :: non_neg_integer()
  def active_count, do: State.active_count()

  @doc "Generates a short human-readable summary of active flags."
  @spec summary() :: String.t()
  def summary, do: State.summary()

  @doc "Converts the current state to a map for serialization."
  @spec to_map() :: map()
  def to_map, do: State.to_map()

  # ── Per-Run Key Delegations ───────────────────────────────────────────

  @doc "Returns the current run key for the calling process."
  @spec get_run_key() :: String.t()
  def get_run_key, do: State.get_run_key()

  @doc "Sets the run key for the calling process."
  @spec set_run_key(String.t()) :: :ok
  def set_run_key(key), do: State.set_run_key(key)

  @doc "Clears the run key for the calling process."
  @spec clear_run_key() :: :ok
  def clear_run_key, do: State.clear_run_key()

  # ── Private ───────────────────────────────────────────────────────────

  # Convert internal %Workflow.State{} to facade %WorkflowState{} struct.
  # This preserves backward compat for callers that pattern-match on
  # the facade struct type rather than the internal one.
  defp to_facade(%State{flags: flags, metadata: metadata, start_time: start_time}) do
    %__MODULE__{flags: flags, metadata: metadata, start_time: start_time}
  end
end
