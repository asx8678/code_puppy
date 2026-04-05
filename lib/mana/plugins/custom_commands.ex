defmodule Mana.Plugins.CustomCommands do
  @moduledoc "Loads custom commands from .mana/commands/ and .claude/commands/"
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
  Loads custom commands from .mana/commands/ and .claude/commands/ directories.
  """
  def load_commands do
    paths = [
      Path.join(Paths.config_dir(), "commands"),
      Path.join(System.get_env("HOME", ""), ".claude/commands")
    ]

    commands = Enum.flat_map(paths, &scan_directory/1)
    :persistent_term.put(@persistent_term_key, commands)
    :ok
  end

  @doc """
  Returns the list of loaded custom commands.
  """
  def loaded_commands do
    :persistent_term.get(@persistent_term_key, [])
  end

  defp scan_directory(dir) do
    case File.ls(dir) do
      {:ok, files} ->
        process_files(files, dir)

      {:error, _} ->
        []
    end
  end

  defp process_files(files, dir) do
    files
    |> Enum.filter(&String.ends_with?(&1, ".md"))
    |> Enum.map(fn file -> load_file(dir, file) end)
    |> Enum.reject(&is_nil/1)
  end

  defp load_file(dir, file) do
    name = Path.rootname(file)
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
    commands = loaded_commands()

    case Enum.find(commands, fn {cmd_name, _} -> cmd_name == name end) do
      {_, template} ->
        result = String.replace(template, "{{args}}", Enum.join(args, " "))
        {:ok, result}

      nil ->
        nil
    end
  end

  @impl true
  def terminate do
    :ok
  end
end
