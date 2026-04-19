defmodule CodePuppyControl.Config.Isolation do
  @moduledoc """
  Guard module enforcing ADR-003 dual-home config isolation.

  Prevents Elixir pup-ex from writing to the Python pup's legacy home
  directory (`~/.code_puppy/`). All file mutations in Elixir pup-ex MUST
  go through the `safe_*` wrappers defined here.

  Direct use of `File.write!/2`, `File.mkdir_p!/1`, `File.rm!/1`, or
  `File.rm_rf/1` on config paths is a violation of ADR-003.

  ## Guard Semantics

  - Paths under the legacy home are **blocked** (write/delete denied).
  - Paths outside the legacy home are **allowed**.
  - Symlink attacks are caught via canonical resolution in `Paths.in_legacy_home?/1`.
  - Blocked violations emit telemetry and raise `IsolationViolation`.

  ## Test Sandbox

  Tests that intentionally need to write to the legacy home use
  `with_sandbox/2` to temporarily lift the guard for specific paths.
  Sandboxes are process-local and nest additively.
  """

  alias CodePuppyControl.Config.Paths

  # ── Exception ───────────────────────────────────────────────────────────

  defmodule IsolationViolation do
    @moduledoc "Raised when an operation targets the legacy home directory."

    defexception [:path, :action, :message]

    @impl true
    def message(%{message: msg}), do: msg
  end

  # ── Safe Wrappers ───────────────────────────────────────────────────────

  @doc """
  Write content to a file, raising `IsolationViolation` if the target
  is under the legacy home directory.
  """
  @spec safe_write!(Path.t(), iodata()) :: :ok
  def safe_write!(path, content) do
    ensure_allowed!(path, :write)
    File.write!(path, content)
  end

  @doc """
  Create a directory tree, raising `IsolationViolation` if the target
  is under the legacy home directory.
  """
  @spec safe_mkdir_p!(Path.t()) :: :ok
  def safe_mkdir_p!(path) do
    ensure_allowed!(path, :mkdir)
    File.mkdir_p!(path)
  end

  @doc """
  Remove a file, raising `IsolationViolation` if the target is under
  the legacy home directory.
  """
  @spec safe_rm!(Path.t()) :: :ok
  def safe_rm!(path) do
    ensure_allowed!(path, :rm)
    File.rm!(path)
  end

  @doc """
  Recursively remove a directory tree, raising `IsolationViolation`
  if the target is under the legacy home directory.
  """
  @spec safe_rm_rf!(Path.t()) :: {:ok, [Path.t()]} | {:error, term(), Path.t()}
  def safe_rm_rf!(path) do
    ensure_allowed!(path, :rm_rf)
    File.rm_rf(path)
  end

  # ── Test Sandbox ─────────────────────────────────────────────────────────

  @doc """
  Temporarily lift the isolation guard for specific paths.

  Stores a per-process whitelist in the process dictionary. When the
  function completes, the previous sandbox state is restored (or removed
  if there was none). Nested sandboxes are additive.

  ## Example

      with_sandbox(["/tmp/test_dir"], fn ->
        safe_write!("/tmp/test_dir/file.txt", "data")
      end)
  """
  @spec with_sandbox([Path.t()], (-> result)) :: result when result: var
  def with_sandbox(paths, fun) when is_list(paths) and is_function(fun, 0) do
    previous = Process.get(:isolation_sandbox)
    new_entries = MapSet.new(Enum.map(paths, &Path.expand/1))

    merged =
      case previous do
        nil -> new_entries
        prev -> MapSet.union(prev, new_entries)
      end

    Process.put(:isolation_sandbox, merged)

    try do
      fun.()
    after
      case previous do
        nil -> Process.delete(:isolation_sandbox)
        prev -> Process.put(:isolation_sandbox, prev)
      end
    end
  end

  # ── Predicate ───────────────────────────────────────────────────────────

  @doc """
  Returns `true` if the path is safe to write to.

  Logic:
    1. Expand path via `Path.expand/1`
    2. If path is in the current process's sandbox → allow
    3. If path is under the legacy home (per `Paths.in_legacy_home?/1`) → deny
    4. Otherwise → allow
  """
  @spec allowed?(Path.t()) :: boolean()
  def allowed?(path) do
    expanded = Path.expand(path)
    sandbox = Process.get(:isolation_sandbox, MapSet.new())

    cond do
      MapSet.member?(sandbox, expanded) -> true
      Paths.in_legacy_home?(path) -> false
      true -> true
    end
  end

  # ── Read-Only Legacy Access ─────────────────────────────────────────────

  @doc """
  Read a file from the legacy home directory.

  Validates that the path is under the legacy home, then reads it.
  This is the ONLY sanctioned way to access files under `~/.code_puppy/`.
  Does NOT provide write capabilities.

  Used by `mix pup_ex.import` (future Phase 3) to copy files from the
  Python pup's home directory.
  """
  @spec read_only_legacy(Path.t()) :: {:ok, binary()} | {:error, File.posix()}
  def read_only_legacy(path) do
    unless Paths.in_legacy_home?(path) do
      raise ArgumentError,
            "read_only_legacy/1 called with path outside legacy home: #{path}"
    end

    File.read(path)
  end

  # ── Private ─────────────────────────────────────────────────────────────

  defp ensure_allowed!(path, action) do
    resolved = Paths.canonical_resolve(path)

    unless allowed?(path) do
      emit_violation_telemetry(resolved, action)

      raise IsolationViolation,
        path: resolved,
        action: action,
        message: "ConfigIsolationViolation: blocked #{action} to #{resolved} (outside Elixir home)"
    end

    :ok
  end

  defp emit_violation_telemetry(resolved_path, action) do
    :telemetry.execute(
      [:code_puppy_control, :config, :isolation_violation],
      %{count: 1},
      %{path: resolved_path, action: action, process: self()}
    )
  end
end
