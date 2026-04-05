defmodule Mana.Agents.JsonLoader do
  @moduledoc """
  Discovers and loads JSON agent configurations.

  Searches multiple directories for agent configuration files:
  - `priv/agents/` - Built-in agent definitions
  - `priv/agents/pack/` - Pack agent definitions (dog-themed agents)
  - `~/.mana/agents/` - User-defined agents

  Agents are loaded with precedence: priv agents override pack agents,
  which override user agents. The first agent with a given name wins.

  ## Usage

      # Discover all available agents
      agents = Mana.Agents.JsonLoader.discover()

      # Load from a specific directory
      agents = Mana.Agents.JsonLoader.load_from_dir("/path/to/agents")

  """

  require Logger

  @user_agents_dir "~/.mana/agents"
  @priv_agents_dir "priv/agents"

  @doc """
  Discover all JSON agent configs from all sources.

  Returns a deduplicated list of agent configurations, with project-level
  agents taking precedence over pack agents, which take precedence over
  user-level agents.

  ## Returns

    List of agent configuration maps, each with a `"_source"` key
    indicating the file path where the config was loaded from.

  """
  @spec discover() :: [map()]
  def discover do
    user_agents = load_from_dir(Path.expand(@user_agents_dir))
    priv_agents = load_from_priv()
    pack_agents = load_from_priv("pack")

    # Project-level overrides pack, which overrides user-level
    all = priv_agents ++ pack_agents ++ user_agents
    deduplicate(all)
  end

  @doc """
  Load agents from a directory.

  ## Parameters

    - `dir` - Path to the directory containing `.json` files

  ## Returns

    List of validated agent configuration maps.

  """
  @spec load_from_dir(String.t()) :: [map()]
  def load_from_dir(dir) do
    case File.ls(dir) do
      {:ok, files} ->
        files
        |> Enum.filter(&String.ends_with?(&1, ".json"))
        |> Enum.map(fn file ->
          path = Path.join(dir, file)
          load_single_file(path)
        end)
        |> Enum.reject(&is_nil/1)

      {:error, reason} ->
        Logger.debug("Could not read agents directory #{dir}: #{inspect(reason)}")
        []
    end
  end

  @doc """
  Load a single agent configuration file.

  ## Parameters

    - `path` - Path to the JSON file

  ## Returns

    - Agent config map on success (with `"_source"` key added)
    - `nil` on failure (invalid JSON, missing required fields, etc.)

  """
  @spec load_single_file(String.t()) :: map() | nil
  def load_single_file(path) do
    case File.read(path) do
      {:ok, data} ->
        case Jason.decode(data) do
          {:ok, config} ->
            validate_config(config, path)

          {:error, reason} ->
            Logger.warning("Invalid JSON in #{path}: #{inspect(reason)}")
            nil
        end

      {:error, reason} ->
        Logger.warning("Could not read #{path}: #{inspect(reason)}")
        nil
    end
  end

  # Load agents from the priv/agents directory (or subdirectory)
  defp load_from_priv(subdir \\ "") do
    dir = Application.app_dir(:mana, Path.join(@priv_agents_dir, subdir))
    load_from_dir(dir)
  end

  # Validate that required fields are present
  defp validate_config(config, path) do
    with name when is_binary(name) <- Map.get(config, "name"),
         desc when is_binary(desc) <- Map.get(config, "description") do
      Map.put(config, "_source", path)
    else
      _ ->
        Logger.warning("Invalid agent config in #{path}: missing required fields")
        nil
    end
  end

  # Deduplicate agents by name, keeping the first occurrence
  defp deduplicate(agents) do
    agents
    |> Enum.group_by(& &1["name"])
    |> Enum.map(fn {_name, configs} -> List.first(configs) end)
  end
end
