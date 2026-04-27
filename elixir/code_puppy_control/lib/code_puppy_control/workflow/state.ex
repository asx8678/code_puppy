defmodule CodePuppyControl.Workflow.State do
  @moduledoc """
  Structured workflow-state tracking for agent runs.

  Full port of Python `code_puppy/workflow_state.py`. Stores a set of
  active flags and optional metadata in an Agent so that multiple
  processes in the same BEAM node can query/mutate the state concurrently.

  ## Migration from Python `workflow_state.py`

  | Python Feature | Elixir Equivalent |
  |----------------|-------------------|
  | `WorkflowFlag` enum | `@all_flags` attribute list |
  | `ContextVar` storage | Agent (named `__MODULE__`) |
  | `set_flag(str)` | String-to-atom conversion via `resolve_flag/1` |
  | `increment_counter/2` | `increment_counter/2` |
  | `detect_and_mark_plan_from_response/2` | `detect_and_mark_plan_from_response/2` |
  | `register_callback_handlers()` | `register_callback_handlers/0` |
  | `unregister_callback_handlers()` | `unregister_callback_handlers/0` |
  | `did_make_api_call` flag | Added (was missing in old WorkflowState) |

  ## Quick start

      # Start in supervision tree
      {CodePuppyControl.Workflow.State, name: CodePuppyControl.Workflow.State}

      # Use the API
      Workflow.State.set_flag(:did_generate_code)
      Workflow.State.has_flag?(:did_generate_code)  #=> true
      Workflow.State.increment_counter("file_edits")
      Workflow.State.reset()
  """

  use Agent

  require Logger

  alias CodePuppyControl.Callbacks

  # ── Flag Definitions ──────────────────────────────────────────────────

  # All workflow flags with descriptions. Mirrors Python's WorkflowFlag enum.
  # NOTE: :did_make_api_call was missing from the original Elixir WorkflowState
  # but is present in the Python source — added here for full parity.
  # TODO(code-puppy-ctj.3): Keep in sync with Python WorkflowFlag enum
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
    {:did_make_api_call, "API call made to model"},
    {:did_edit_file, "File edited"},
    {:did_create_file, "File created"},
    {:did_delete_file, "File deleted"},
    {:did_run_tests, "Tests run"},
    {:did_check_lint, "Linting performed"}
  ]

  @flag_names Enum.map(@all_flags, fn {name, _desc} -> name end)

  # String-to-atom lookup map for efficient resolution
  @flag_by_string @all_flags
                  |> Enum.map(fn {name, _desc} -> {Atom.to_string(name), name} end)
                  |> Enum.into(%{})
                  |> Map.merge(
                    # Also support uppercase snake_case (Python enum name format)
                    @all_flags
                    |> Enum.map(fn {name, _desc} ->
                      {name |> Atom.to_string() |> String.upcase(), name}
                    end)
                    |> Enum.into(%{})
                  )

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

  @doc """
  Resolves a flag from atom or string to its canonical atom form.

  Supports both atom and string inputs. Strings are matched case-insensitively
  against known flag names (e.g. `"did_generate_code"`, `"DID_GENERATE_CODE"`
  all resolve to `:did_generate_code`).

  Returns `{:ok, atom}` if the flag is known, `{:error, :unknown_flag}` otherwise.
  """
  @spec resolve_flag(atom() | String.t()) :: {:ok, atom()} | {:error, :unknown_flag}
  def resolve_flag(name) when is_atom(name) do
    if known_flag?(name), do: {:ok, name}, else: {:error, :unknown_flag}
  end

  def resolve_flag(name) when is_binary(name) do
    case Map.get(@flag_by_string, name) do
      nil ->
        # Try case-insensitive lookup
        name_lower = String.downcase(name)

        Enum.find_value(@all_flags, {:error, :unknown_flag}, fn {atom, _desc} ->
          if Atom.to_string(atom) == name_lower, do: {:ok, atom}
        end)

      atom ->
        {:ok, atom}
    end
  end

  # ── State Struct ──────────────────────────────────────────────────────

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

  # ── Agent API ─────────────────────────────────────────────────────────

  @doc """
  Starts the Workflow.State agent.

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

  # ── Flag Operations ───────────────────────────────────────────────────

  @doc """
  Sets a flag (adds it to the active set).

  Accepts both atoms and strings. Unknown flags are ignored with a warning.

  ## Examples

      Workflow.State.set_flag(:did_generate_code)
      Workflow.State.set_flag("did_generate_code")
      Workflow.State.set_flag("DID_GENERATE_CODE")
  """
  @spec set_flag(atom() | String.t()) :: :ok
  def set_flag(flag) when is_atom(flag) or is_binary(flag) do
    case resolve_flag(flag) do
      {:ok, resolved} ->
        Agent.update(__MODULE__, fn state ->
          %{state | flags: MapSet.put(state.flags, resolved)}
        end)

      {:error, :unknown_flag} ->
        Logger.warning("Unknown workflow flag: #{inspect(flag)}")
    end

    :ok
  end

  @doc """
  Sets a flag with explicit boolean value.

  When `value` is `true`, adds the flag. When `false`, removes it.
  """
  @spec set_flag(atom() | String.t(), boolean()) :: :ok
  def set_flag(flag, true) when is_atom(flag) or is_binary(flag) do
    set_flag(flag)
  end

  def set_flag(flag, false) when is_atom(flag) or is_binary(flag) do
    clear_flag(flag)
  end

  @doc """
  Clears a flag (removes it from the active set). Unknown flags are ignored.
  """
  @spec clear_flag(atom() | String.t()) :: :ok
  def clear_flag(flag) when is_atom(flag) or is_binary(flag) do
    case resolve_flag(flag) do
      {:ok, resolved} ->
        Agent.update(__MODULE__, fn state ->
          %{state | flags: MapSet.delete(state.flags, resolved)}
        end)

      {:error, :unknown_flag} ->
        # Silently ignore unknown flags on clear (matching Python behavior)
        :ok
    end

    :ok
  end

  @doc """
  Checks whether a flag is active.

  Accepts both atoms and strings. Returns `false` for unknown flags.
  """
  @spec has_flag?(atom() | String.t()) :: boolean()
  def has_flag?(flag) when is_atom(flag) or is_binary(flag) do
    case resolve_flag(flag) do
      {:ok, resolved} ->
        Agent.get(__MODULE__, fn state -> MapSet.member?(state.flags, resolved) end)

      {:error, :unknown_flag} ->
        false
    end
  end

  # ── Metadata Operations ───────────────────────────────────────────────

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

  @doc """
  Increments a counter in metadata.

  If the key doesn't exist, it starts at 0 and is incremented by `amount`.
  Returns the new counter value.

  ## Examples

      iex> Workflow.State.increment_counter("file_edits")
      1

      iex> Workflow.State.increment_counter("api_calls", 5)
      5
  """
  @spec increment_counter(String.t(), integer()) :: integer()
  def increment_counter(key, amount \\ 1) when is_binary(key) and is_integer(amount) do
    Agent.get_and_update(__MODULE__, fn state ->
      current = Map.get(state.metadata, key, 0)
      new_value = current + amount
      {{:ok, new_value}, %{state | metadata: Map.put(state.metadata, key, new_value)}}
    end)
    |> case do
      {:ok, value} -> value
    end
  end

  # ── Introspection ─────────────────────────────────────────────────────

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

  # ── Plan Detection ────────────────────────────────────────────────────

  @doc """
  Parse the given response text; if it contains a plan, set DID_CREATE_PLAN.

  Returns `true` iff `:did_create_plan` was set as a result of this call.

  Uses a heuristic: looks for ordered list items (numbered or bulleted)
  with at least `min_tasks` entries. This mirrors the Python
  `detect_and_mark_plan_from_response` which delegates to
  `subtask_parser.has_plan`.

  ## TODO(code-puppy-ctj.3): Wire to a proper Elixir subtask parser when available

  The Python version delegates to `code_puppy.utils.subtask_parser.has_plan`.
  A proper Elixir implementation should be wired when the subtask parser
  is ported. For now, this uses a regex-based heuristic that matches
  numbered task patterns like "1.", "2.", etc.
  """
  @spec detect_and_mark_plan_from_response(String.t(), keyword()) :: boolean()
  def detect_and_mark_plan_from_response(response_text, opts \\ [])
      when is_binary(response_text) do
    min_tasks = Keyword.get(opts, :min_tasks, 2)

    if has_plan?(response_text, min_tasks) do
      set_flag(:did_create_plan)
      true
    else
      false
    end
  end

  # Heuristic plan detection: counts numbered list items.
  # Matches patterns like "1. task", "2) task", "- task", "* task"
  # across multiple lines. Returns true if count >= min_tasks.
  # TODO(code-puppy-ctj.3): Replace with proper subtask parser when ported
  defp has_plan?(text, min_tasks) do
    # Count numbered items (e.g. "1. Do X", "2) Do Y")
    numbered_count =
      Regex.scan(~r/(?:^|\n)\s*(\d+)[.)]\s+\S/, text)
      |> length()

    # Count bullet items (e.g. "- Do X", "* Do Y")
    bullet_count =
      Regex.scan(~r/(?:^|\n)\s*[-*]\s+\S/, text)
      |> length()

    # A plan is detected if there are enough items of either type
    numbered_count >= min_tasks or bullet_count >= min_tasks
  end

  # ── Callback Integration ───────────────────────────────────────────────

  # Callback handler functions (defined at module level so they can be unregistered)

  @doc false
  def _on_delete_file(_context) do
    set_flag(:did_delete_file)
  end

  @doc false
  def _on_run_shell_command(_context, command, _cwd \\ nil, _timeout \\ 60) do
    set_flag(:did_execute_shell)

    cmd_lower = if is_binary(command), do: String.downcase(command), else: ""

    # Track specific tool usage
    if String.contains?(cmd_lower, "test") or String.contains?(cmd_lower, "pytest") do
      set_flag(:did_run_tests)
    end

    if String.contains?(cmd_lower, "lint") or
         String.contains?(cmd_lower, "flake8") or
         String.contains?(cmd_lower, "pylint") or
         String.contains?(cmd_lower, "ruff") do
      set_flag(:did_check_lint)
    end
  end

  @doc false
  def _on_agent_run_start(agent_name, model_name, _session_id \\ nil) do
    reset()
    put_metadata("agent_name", agent_name)
    put_metadata("model_name", model_name)
  end

  @doc false
  def _on_agent_run_end(agent_name, model_name, session_id \\ nil, success \\ true, error \\ nil, metadata \\ nil) do
    _ = {agent_name, model_name, session_id, error, metadata}

    if not success do
      set_flag(:did_encounter_error)
    end

    put_metadata("end_time", System.system_time(:second))
    put_metadata("success", success)
  end

  @doc false
  def _on_pre_tool_call(tool_name, _tool_args, _context \\ nil) do
    tool_name_str = if is_atom(tool_name), do: Atom.to_string(tool_name), else: tool_name

    # Track context loading
    if tool_name_str in ["read_file", "list_files", "grep", "search_files"] do
      set_flag(:did_load_context)
    end

    # Track shell execution
    if tool_name_str == "agent_run_shell_command" do
      set_flag(:did_execute_shell)
    end

    # Track file creation
    if tool_name_str == "create_file" do
      set_flag(:did_create_file)
      set_flag(:did_generate_code)
    end

    # Track file editing
    if tool_name_str in ["replace_in_file", "delete_snippet", "edit_file"] do
      set_flag(:did_edit_file)
      set_flag(:did_generate_code)
    end

    # Track API calls
    if tool_name_str in ["invoke_agent"] do
      set_flag(:did_make_api_call)
    end
  end

  @doc """
  Register handlers for existing callbacks to auto-set workflow flags.

  This wires the workflow state into the callback system so that
  flags are set automatically based on tool calls, agent lifecycle,
  and shell commands. Call this during application startup or plugin init.
  """
  @spec register_callback_handlers() :: :ok
  def register_callback_handlers do
    Callbacks.register(:delete_file, &_on_delete_file/1)

    Callbacks.register(:run_shell_command, &_on_run_shell_command/4)

    Callbacks.register(:agent_run_start, &_on_agent_run_start/3)

    Callbacks.register(:agent_run_end, &_on_agent_run_end/6)

    Callbacks.register(:pre_tool_call, &_on_pre_tool_call/3)

    Logger.debug("Workflow.State callback handlers registered")
    :ok
  end

  @doc """
  Unregister all workflow state callback handlers.

  Useful for test teardown or clean shutdown.
  """
  @spec unregister_callback_handlers() :: :ok
  def unregister_callback_handlers do
    Callbacks.unregister(:delete_file, &_on_delete_file/1)
    Callbacks.unregister(:run_shell_command, &_on_run_shell_command/4)
    Callbacks.unregister(:agent_run_start, &_on_agent_run_start/3)
    Callbacks.unregister(:agent_run_end, &_on_agent_run_end/6)
    Callbacks.unregister(:pre_tool_call, &_on_pre_tool_call/3)

    Logger.debug("Workflow.State callback handlers unregistered")
    :ok
  end
end
