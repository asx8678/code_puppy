defmodule Mana.Plugins.CustomCommands do
  @moduledoc """
  Loads custom markdown commands from multiple directories.

  Scans the following directories in order (later directories override
  earlier ones with the same command name — Map.merge last-wins convention):

  1. `~/.mana/commands/` — Mana-native global commands (lowest)
  2. `~/.code-puppy/commands/` — Code Puppy Python compatibility
  3. `~/.claude/commands/` — Claude-compatible global commands
  4. `<cwd>/.claude/commands/` — Project-local Claude commands
  5. `<cwd>/.agents/commands/` — Project-local agent commands
  6. `<cwd>/.github/prompts/` — GitHub Copilot prompts (*.prompt.md) (highest)

  Path 6 gives `.github/prompts` highest precedence so that project-maintained
  GitHub Copilot-style prompts override per-developer agent commands. This
  mirrors how `.github/prompts` is typically committed to the repo while
  `.agents/commands` may be developer-local.

  Path 4 (`<cwd>/.claude/commands`) is included for symmetry with the global
  `~/.claude/commands` path, matching Claude Code's project-local convention
  and giving teams a second project-scoped location alongside `.agents/commands`.

  Commands are stored in `:persistent_term` for O(1) read access.
  Uses the `:custom_command` hook for dispatch (not Mana.Commands.Registry).
  """
  @behaviour Mana.Plugin.Behaviour

  alias Mana.Config.Paths

  @persistent_term_key {__MODULE__, :commands}

  @impl true
  def name, do: "custom_commands"

  @impl true
  def init(config) do
    # Load commands on startup
    load_commands()
    {:ok, %{config: config}}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.load_commands/0},
      {:custom_command, &__MODULE__.execute_command/2}
    ]
  end

  @doc """
  Returns the default command search paths.

  Each entry is `{directory, suffix}` where `directory` is scanned for files
  ending in `suffix`. The list is ordered by ascending precedence — later
  entries override earlier ones when command names collide.

  See the module doc for the full precedence rationale.
  """
  def default_paths do
    home = System.get_env("HOME", "")
    cwd = File.cwd!()

    [
      {Path.join(Paths.config_dir(), "commands"), ".md"},
      {Path.join(home, ".code-puppy/commands"), ".md"},
      {Path.join(home, ".claude/commands"), ".md"},
      {Path.join(cwd, ".claude/commands"), ".md"},
      {Path.join(cwd, ".agents/commands"), ".md"},
      {Path.join(cwd, ".github/prompts"), ".prompt.md"}
    ]
  end

  @doc """
  Loads custom commands from the given `paths`, or `default_paths/0` if none.

  Later entries in `paths` override earlier ones when command names collide
  (project-local commands take precedence over global ones).
  """
  def load_commands(paths \\ default_paths()) do
    commands =
      paths
      |> Enum.flat_map(fn {dir, suffix} -> scan_directory(dir, suffix) end)
      |> Enum.into(%{})

    :persistent_term.put(@persistent_term_key, commands)
    :ok
  end

  @doc """
  Returns the list of loaded custom commands as `{name, content}` tuples.
  """
  def loaded_commands do
    :persistent_term.get(@persistent_term_key, %{}) |> Map.to_list()
  end

  defp scan_directory(dir, suffix) do
    case File.ls(dir) do
      {:ok, files} ->
        process_files(files, dir, suffix)

      {:error, _} ->
        []
    end
  end

  defp process_files(files, dir, suffix) do
    files
    |> Enum.filter(&String.ends_with?(&1, suffix))
    |> Enum.map(fn file -> load_file(dir, file, suffix) end)
    |> Enum.reject(&is_nil/1)
  end

  defp load_file(dir, file, suffix) do
    name = String.replace_suffix(file, suffix, "")
    full_path = Path.join(dir, file)

    case File.read(full_path) do
      {:ok, content} -> {name, content}
      {:error, _} -> nil
    end
  end

  @doc """
  Executes a custom command if found.
  Returns {:ok, result} if executed, nil if command not found.
  """
  def execute_command(name, args) do
    commands = :persistent_term.get(@persistent_term_key, %{})

    case Map.get(commands, name) do
      nil ->
        nil

      template ->
        result = String.replace(template, "{{args}}", Enum.join(args, " "))
        {:ok, result}
    end
  end

  @impl true
  def terminate do
    :ok
  end
end
