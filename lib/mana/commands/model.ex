defmodule Mana.Commands.Model do
  @moduledoc """
  Model switching and management commands.

  Provides commands for listing, setting, and querying AI model configurations.

  ## Commands

  - `/model list` - List all available models
  - `/model set <name>` - Set the current model
  - `/model current` - Show the current model

  ## Examples

      /model list
      # Shows: Available models: claude-opus-4-6 (anthropic), gpt-4 (openai), ...

      /model set claude-opus-4-6
      # Shows: Model set to: claude-opus-4-6

      /model current
      # Shows: Current model: claude-opus-4-6
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Config.Store, as: ConfigStore
  alias Mana.Models.Registry, as: ModelsRegistry

  @impl true
  def name, do: "/model"

  @impl true
  def description, do: "Manage AI models"

  @impl true
  def usage, do: "/model [list|set <name>|current]"

  @impl true
  def execute(["list"], _context) do
    models = ModelsRegistry.list_models()

    if map_size(models) == 0 do
      {:ok, "No models registered."}
    else
      formatted =
        Enum.map_join(models, "\n", fn {name, config} ->
          provider = Map.get(config, "provider") || Map.get(config, :provider, "unknown")
          "  #{name} (#{provider})"
        end)

      {:ok, "Available models:\n#{formatted}"}
    end
  end

  def execute(["set", name], _context) do
    case ModelsRegistry.get_model(name) do
      {:ok, _config} ->
        ConfigStore.put(:current_model, name)
        {:ok, "Model set to: #{name}"}

      {:error, :not_found} ->
        {:error, "Model not found: #{name}"}
    end
  end

  def execute(["current"], _context) do
    model = ConfigStore.get(:current_model) || "claude-opus-4-6"
    {:ok, "Current model: #{model}"}
  end

  def execute([], _context) do
    {:ok, "Usage: #{usage()}"}
  end

  def execute(_args, _context) do
    {:ok, "Usage: #{usage()}"}
  end
end

defmodule Mana.Commands.AddModel do
  @moduledoc """
  Command to add a custom model configuration.

  ## Usage

      /add_model <name> <provider> [max_tokens] [supports_tools]

  ## Examples

      /add_model my-gpt-4 openai 4096 true
      /add_model local-llm ollama 2048 false
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Models.Registry, as: ModelsRegistry

  @impl true
  def name, do: "/add_model"

  @impl true
  def description, do: "Add a custom model configuration"

  @impl true
  def usage, do: "/add_model <name> <provider> [max_tokens] [supports_tools]"

  @impl true
  def execute([name, provider | opts], _context) do
    max_tokens = parse_max_tokens(opts)
    supports_tools = parse_supports_tools(opts)

    config = %{
      provider: provider,
      max_tokens: max_tokens,
      supports_tools: supports_tools
    }

    ModelsRegistry.register_model(name, config)
    {:ok, "Added model: #{name} (#{provider})"}
  end

  def execute(_args, _context) do
    {:ok, "Usage: #{usage()}"}
  end

  defp parse_max_tokens([max_tokens_str, _ | _]) do
    case Integer.parse(max_tokens_str) do
      {n, _} -> n
      :error -> 4096
    end
  end

  defp parse_max_tokens([max_tokens_str]) do
    case Integer.parse(max_tokens_str) do
      {n, _} -> n
      :error -> 4096
    end
  end

  defp parse_max_tokens(_), do: 4096

  defp parse_supports_tools([_, tools_str]) do
    tools_str in ["true", "yes", "1"]
  end

  defp parse_supports_tools([tools_str]) do
    tools_str in ["true", "yes", "1"]
  end

  defp parse_supports_tools(_), do: true
end
