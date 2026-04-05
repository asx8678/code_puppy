defmodule Mana.RepoCompass do
  @moduledoc "AST-based project context injection for agent awareness"
  @behaviour Mana.Plugin.Behaviour

  alias Mana.RepoCompass.Formatter
  alias Mana.RepoCompass.Indexer

  @impl true
  def name, do: "repo_compass"

  @impl true
  def init(_config) do
    {:ok, %{enabled: enabled?()}}
  end

  @impl true
  def hooks do
    [
      {:get_model_system_prompt, &__MODULE__.on_get_model_system_prompt/2}
    ]
  end

  @impl true
  def terminate do
    :ok
  end

  @doc false
  def on_get_model_system_prompt(_model_name, _default_prompt) do
    if enabled?() do
      project_dir = Mana.Config.get(:project_dir, File.cwd!())
      project_name = Path.basename(project_dir)

      index =
        Indexer.index(project_dir,
          max_files: get_config(:max_files, 100),
          max_symbols_per_file: get_config(:max_symbols_per_file, 10)
        )

      compass_text = Formatter.format(index, project_name)

      %{prompt: compass_text}
    else
      nil
    end
  end

  defp enabled?, do: get_config(:enabled, true)

  defp get_config(key, default) do
    case Mana.Config.get(:repo_compass, %{}) do
      nil -> default
      config -> Map.get(config, key, default)
    end
  end
end
