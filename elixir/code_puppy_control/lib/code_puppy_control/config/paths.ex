defmodule CodePuppyControl.Config.Paths do
  @moduledoc """
  XDG-compatible path resolution for Code Puppy directories and files.

  Resolves paths using the XDG Base Directory specification with these
  priority rules:

  1. `PUP_HOME` env var — overrides all other paths (project convention)
  2. `PUPPY_HOME` env var — legacy support with deprecation warning
  3. XDG env vars (`XDG_CONFIG_HOME`, etc.) — standard XDG
  4. Default `~/.code_puppy` — fallback for all file types

  ## Path Layout

  ```
  ~/.code_puppy/
  ├── puppy.cfg           # Main config (INI format)
  ├── mcp_servers.json    # MCP server definitions
  ├── models.json         # Model registry
  ├── extra_models.json   # User-added models
  ├── agents/             # Agent definitions
  ├── skills/             # Skill definitions
  ├── contexts/           # Context presets
  ├── autosaves/          # Session autosaves (cache)
  ├── command_history.txt # Command history (state)
  └── dbos_store.sqlite   # DBOS state store
  ```

  When XDG env vars are set, files split across config/data/cache/state
  directories per the spec. Otherwise everything lives under `~/.code_puppy`.
  """

  @home_dir Path.expand("~")

  # ── Base directories ────────────────────────────────────────────────────

  @doc """
  Root directory for all Code Puppy files.

  Resolution order: `PUP_HOME` → `PUPPY_HOME` (legacy) → `~/.code_puppy`.
  """
  @spec home_dir() :: String.t()
  def home_dir do
    System.get_env("PUP_HOME") ||
      System.get_env("PUPPY_HOME") ||
      Path.join(@home_dir, ".code_puppy")
  end

  @doc """
  Configuration directory. Contains `puppy.cfg`, `mcp_servers.json`.

  Uses `XDG_CONFIG_HOME/code_puppy` if set, otherwise falls back to `home_dir/`.
  """
  @spec config_dir() :: String.t()
  def config_dir do
    xdg_dir("XDG_CONFIG_HOME", ".config")
  end

  @doc """
  Data directory. Contains `models.json`, `agents/`, `skills/`.

  Uses `XDG_DATA_HOME/code_puppy` if set, otherwise falls back to `home_dir/`.
  """
  @spec data_dir() :: String.t()
  def data_dir do
    xdg_dir("XDG_DATA_HOME", ".local/share")
  end

  @doc """
  Cache directory. Contains autosaves and temporary data.

  Uses `XDG_CACHE_HOME/code_puppy` if set, otherwise falls back to `home_dir/`.
  """
  @spec cache_dir() :: String.t()
  def cache_dir do
    xdg_dir("XDG_CACHE_HOME", ".cache")
  end

  @doc """
  State directory. Contains command history and persistent runtime state.

  Uses `XDG_STATE_HOME/code_puppy` if set, otherwise falls back to `home_dir/`.
  """
  @spec state_dir() :: String.t()
  def state_dir do
    xdg_dir("XDG_STATE_HOME", ".local/state")
  end

  # ── Config files ────────────────────────────────────────────────────────

  @doc "Path to the main config file `puppy.cfg`."
  @spec config_file() :: String.t()
  def config_file, do: Path.join(config_dir(), "puppy.cfg")

  @doc "Path to the MCP servers config file."
  @spec mcp_servers_file() :: String.t()
  def mcp_servers_file, do: Path.join(config_dir(), "mcp_servers.json")

  # ── Data files ──────────────────────────────────────────────────────────

  @doc "Path to the model registry JSON file."
  @spec models_file() :: String.t()
  def models_file, do: Path.join(data_dir(), "models.json")

  @doc "Path to user-added extra models file."
  @spec extra_models_file() :: String.t()
  def extra_models_file, do: Path.join(data_dir(), "extra_models.json")

  @doc "Path to the agents directory."
  @spec agents_dir() :: String.t()
  def agents_dir, do: Path.join(data_dir(), "agents")

  @doc "Path to the skills directory."
  @spec skills_dir() :: String.t()
  def skills_dir, do: Path.join(data_dir(), "skills")

  @doc "Path to the contexts directory."
  @spec contexts_dir() :: String.t()
  def contexts_dir, do: Path.join(data_dir(), "contexts")

  # ── Cache files ─────────────────────────────────────────────────────────

  @doc "Path to the autosaves directory."
  @spec autosave_dir() :: String.t()
  def autosave_dir, do: Path.join(cache_dir(), "autosaves")

  # ── State files ─────────────────────────────────────────────────────────

  @doc "Path to the command history file."
  @spec command_history_file() :: String.t()
  def command_history_file, do: Path.join(state_dir(), "command_history.txt")

  # ── Utilities ───────────────────────────────────────────────────────────

  @doc """
  Ensure all standard directories exist with `0o700` permissions.
  Returns `:ok`.
  """
  @spec ensure_dirs!() :: :ok
  def ensure_dirs! do
    for dir <- [config_dir(), data_dir(), cache_dir(), state_dir(), skills_dir()] do
      File.mkdir_p!(dir)
      # Best-effort permission set (no-op on some platforms)
      File.chmod(dir, 0o700)
    end

    :ok
  end

  @doc """
  Return a project-local agents directory if `.code_puppy/agents/` exists
  in the current working directory, or `nil`.
  """
  @spec project_agents_dir() :: String.t() | nil
  def project_agents_dir do
    path = Path.join(File.cwd!(), ".code_puppy/agents")
    if File.dir?(path), do: path, else: nil
  end

  # ── Private ─────────────────────────────────────────────────────────────

  defp xdg_dir(xdg_var, _fallback_subdir) do
    # If PUP_HOME is set, everything goes under it
    case System.get_env("PUP_HOME") do
      nil -> xdg_or_legacy(xdg_var)
      home -> home
    end
  end

  defp xdg_or_legacy(xdg_var) do
    case System.get_env(xdg_var) do
      nil ->
        # Legacy: check PUPPY_HOME, then default ~/.code_puppy
        System.get_env("PUPPY_HOME") ||
          Path.join(@home_dir, ".code_puppy")

      xdg_base ->
        Path.join(xdg_base, "code_puppy")
    end
  end
end
