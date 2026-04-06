defmodule Mana.Prompt.Compositor do
  @moduledoc """
  7-layer prompt assembly pipeline.

  Takes an agent definition, model name, and options to produce
  a final system prompt string through a composable 7-layer process:

  1. Agent's system_prompt field
  2. load_prompt callbacks (optional, ~10 agents opt in)
  3. Environment context
  4. Identity block
  5. Rules (AGENTS.md)
  6. Metadata (current date, working dir, etc)
  7. Model-specific transform

  ## Usage

      agent_def = %{system_prompt: "You are a helpful assistant."}
      prompt = Mana.Prompt.Compositor.assemble(agent_def, "claude-3-opus", cwd: "/path/to/project")

  ## Layer Ordering

  Layers are assembled in order and joined with double newlines.
  Each layer can add zero or more text blocks to the final prompt.
  """

  alias Mana.Prompt.Environment
  alias Mana.Prompt.Identity
  alias Mana.Prompt.ModelTransform
  alias Mana.Prompt.Rules

  @doc """
  Assembles a system prompt through the 7-layer pipeline.

  ## Parameters

    - agent_def: Map containing agent definition, may include :system_prompt
    - model_name: String model identifier (e.g., "claude-3-opus", "gpt-4")
    - opts: Keyword list of options including :cwd for working directory

  ## Returns

    Final prompt string with all layers joined

  ## Examples

      iex> Mana.Prompt.Compositor.assemble(%{system_prompt: "Hello"}, "claude-3")
      "Hello\\n\\n## Environment\\n..."

  """
  @spec assemble(map(), String.t(), keyword()) :: String.t()
  def assemble(agent_def, model_name, opts \\ []) do
    []
    |> layer_1_system_prompt(agent_def)
    |> layer_2_load_prompt_callbacks(agent_def)
    |> layer_3_environment()
    |> layer_4_identity()
    |> layer_5_rules()
    |> layer_6_metadata(opts)
    |> layer_7_model_transform(model_name)
    |> Enum.join("\n\n")
  end

  # L1: Agent's system_prompt field
  defp layer_1_system_prompt(layers, agent_def) do
    case Map.get(agent_def, :system_prompt) do
      nil ->
        layers

      prompt when is_binary(prompt) ->
        layers ++ [prompt]

      prompt_fn when is_function(prompt_fn, 0) ->
        layers ++ [prompt_fn.()]
    end
  end

  # L2: Fire :load_prompt callbacks (only ~10 agents opt in)
  # IMPORTANT: load_prompt fires INSIDE get_system_prompt, NOT after it
  defp layer_2_load_prompt_callbacks(layers, _agent_def) do
    case Mana.Callbacks.dispatch(:load_prompt, []) do
      {:ok, results} when is_list(results) ->
        extra = Enum.filter(results, &is_binary/1)
        layers ++ extra

      _ ->
        layers
    end
  end

  # L3: Environment context
  defp layer_3_environment(layers) do
    layers ++ [Environment.block()]
  end

  # L4: Identity
  defp layer_4_identity(layers) do
    layers ++ [Identity.block()]
  end

  # L5: Rules (AGENTS.md)
  defp layer_5_rules(layers) do
    layers ++ [Rules.load()]
  end

  # L6: Metadata (current date, working dir, etc)
  defp layer_6_metadata(layers, opts) do
    layers ++ [Environment.metadata_block(opts)]
  end

  # L7: Model-specific transform
  defp layer_7_model_transform(layers, model_name) do
    ModelTransform.apply(layers, model_name)
  end
end
