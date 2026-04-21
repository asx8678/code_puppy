defmodule CodePuppyControl.WorkflowState do
  @moduledoc """
  Structured workflow-state tracking for agent runs.

  Mirrors the Python `code_puppy.workflow_state` module. Stores a set of
  active flags and optional metadata in an Agent so that multiple processes
  in the same BEAM node can query/mutate the state concurrently.

  ## Quick start

      WorkflowState.start_link()          # typically in a supervision tree
      WorkflowState.set_flag(:did_generate_code)
      WorkflowState.has_flag?(:did_generate_code)  #=> true
      WorkflowState.reset()
  """

  use Agent

  # ── Flag Definitions ──────────────────────────────────────────────────────

  @all_flags [
    {:did_generate_code, "Code was generated/modified"},
    {:did_execute_shell, "Shell command executed"},
    {:did_load_context, "Context/files loaded"},
    {:did_create_plan, "Plan created"},
    {:did_encounter_error, "Error occurred"},
    {:needs_user_confirmation, "User confirmation pending"},
    {:did_save_session, "Session saved"},
    {:did_use_fallback_model, "Fallback model used"},
    {:did_trigger_compaction, "Context compacted"},
    {:did_edit_file, "File edited"},
    {:did_create_file, "File created"},
    {:did_delete_file, "File deleted"},
    {:did_run_tests, "Tests run"},
    {:did_check_lint, "Linting performed"}
  ]

  @flag_names Enum.map(@all_flags, fn {name, _desc} -> name end)

  @doc "Returns all known flag definitions as `[{atom, description}]`."
  @spec all_flags() :: [{atom(), String.t()}]
  def all_flags, do: @all_flags

  @doc "Returns all known flag name atoms."
  @spec flag_names() :: [atom()]
  def flag_names, do: @flag_names

  @doc "Checks whether `name` is a known flag atom."
  @spec known_flag?(atom()) :: boolean()
  def known_flag?(name) when is_atom(name), do: name in @flag_names

  def known_flag?(_), do: false

  # ── State Struct ──────────────────────────────────────────────────────────

  defstruct flags: MapSet.new(), metadata: %{}, start_time: nil

  @type t :: %__MODULE__{
          flags: MapSet.t(atom()),
          metadata: %{String.t() => any()},
          start_time: integer() | nil
        }

  @doc "Creates a fresh workflow state struct."
  @spec new() :: t()
  def new do
    %__MODULE__{start_time: System.system_time(:second)}
  end

  # ── Agent API ─────────────────────────────────────────────────────────────

  @doc """
  Starts the WorkflowState agent (unnamed, caller-supervised).

  For application-wide state, use `start_link/1` with `name: __MODULE__`.
  """
  @spec start_link(keyword()) :: Agent.on_start()
  def start_link(opts \\ []) do
    Agent.start_link(fn -> new() end, opts)
  end

  @doc "Returns the current workflow state."
  @spec get() :: t()
  def get do
    Agent.get(__MODULE__, & &1)
  end

  @doc "Resets to a fresh workflow state and returns it."
  @spec reset() :: t()
  def reset do
    fresh = new()
    Agent.update(__MODULE__, fn _ -> fresh end)
    fresh
  end

  @doc "Sets a flag (adds it to the active set). Unknown flags are ignored."
  @spec set_flag(atom()) :: :ok
  def set_flag(flag) when is_atom(flag) do
    if known_flag?(flag) do
      Agent.update(__MODULE__, fn state ->
        %{state | flags: MapSet.put(state.flags, flag)}
      end)
    end

    :ok
  end

  @doc "Clears a flag (removes it from the active set). Unknown flags are ignored."
  @spec clear_flag(atom()) :: :ok
  def clear_flag(flag) when is_atom(flag) do
    if known_flag?(flag) do
      Agent.update(__MODULE__, fn state ->
        %{state | flags: MapSet.delete(state.flags, flag)}
      end)
    end

    :ok
  end

  @doc "Checks whether a flag is active. Returns `false` for unknown flags."
  @spec has_flag?(atom()) :: boolean()
  def has_flag?(flag) when is_atom(flag) do
    if known_flag?(flag) do
      Agent.get(__MODULE__, fn state -> MapSet.member?(state.flags, flag) end)
    else
      false
    end
  end

  @doc "Stores a metadata key/value pair."
  @spec put_metadata(String.t(), any()) :: :ok
  def put_metadata(key, value) when is_binary(key) do
    Agent.update(__MODULE__, fn state ->
      %{state | metadata: Map.put(state.metadata, key, value)}
    end)
  end

  @doc "Reads a metadata value, defaulting to `default`."
  @spec get_metadata(String.t(), any()) :: any()
  def get_metadata(key, default \\ nil) when is_binary(key) do
    Agent.get(__MODULE__, fn state -> Map.get(state.metadata, key, default) end)
  end

  @doc "Returns a map of current metadata."
  @spec metadata() :: %{String.t() => any()}
  def metadata do
    Agent.get(__MODULE__, fn state -> state.metadata end)
  end

  @doc "Returns the count of active flags."
  @spec active_count() :: non_neg_integer()
  def active_count do
    Agent.get(__MODULE__, fn state -> MapSet.size(state.flags) end)
  end

  @doc "Generates a short human-readable summary of active flags."
  @spec summary() :: String.t()
  def summary do
    state = get()

    if MapSet.size(state.flags) == 0 do
      "No actions recorded"
    else
      state.flags
      |> Enum.map(&Atom.to_string/1)
      |> Enum.map(&String.replace(&1, "_", " "))
      |> Enum.map(&String.capitalize/1)
      |> Enum.sort()
      |> Enum.join(", ")
    end
  end

  @doc "Converts the current state to a map for serialization."
  @spec to_map() :: map()
  def to_map do
    state = get()

    %{
      flags: state.flags |> MapSet.to_list() |> Enum.map(&Atom.to_string/1),
      metadata: state.metadata,
      start_time: state.start_time,
      summary: summary()
    }
  end
end
