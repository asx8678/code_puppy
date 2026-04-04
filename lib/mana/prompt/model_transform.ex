defmodule Mana.Prompt.ModelTransform do
  @moduledoc """
  Model-specific prompt transformation.

  Applies model-specific wrapping and transformations to the assembled
  prompt layers. Supports Claude (direct), Antigravity (envelope), and
  extensible via :get_model_system_prompt callbacks.
  """

  @doc """
  Applies model-specific transformations to the prompt layers.

  First attempts to use :get_model_system_prompt callbacks for custom
  transformations, then falls back to default transforms based on
  model name patterns.

  ## Parameters

    - layers: List of prompt layer strings
    - model_name: String model identifier

  ## Returns

    List of transformed prompt layers (usually a single wrapped string)

  ## Examples

      iex> Mana.Prompt.ModelTransform.apply(["Hello"], "claude-3")
      ["Hello"]

      iex> Mana.Prompt.ModelTransform.apply(["Hello"], "antigravity-model")
      ["<antigravity>\\nHello\\n</antigravity>"]

  """
  @spec apply([String.t()], String.t()) :: [String.t()]
  def apply(layers, model_name) when is_list(layers) and is_binary(model_name) do
    prompt = Enum.join(layers, "\n\n")

    # Fire :get_model_system_prompt callbacks for per-model customization
    # Callbacks receive: [model_name, default_prompt]
    case Mana.Callbacks.dispatch(:get_model_system_prompt, [model_name, prompt]) do
      {:ok, results} when is_list(results) ->
        # Find first callback that returns a map with :prompt key
        custom_result =
          Enum.find(results, fn
            %{prompt: custom_prompt} when is_binary(custom_prompt) -> true
            _ -> false
          end)

        case custom_result do
          %{prompt: custom_prompt} -> [custom_prompt]
          _ -> apply_default_transform(prompt, model_name)
        end

      _ ->
        apply_default_transform(prompt, model_name)
    end
  end

  defp apply_default_transform(prompt, model_name) do
    model_lower = String.downcase(model_name)

    cond do
      String.contains?(model_lower, "claude") ->
        claude_wrapper(prompt)

      String.contains?(model_lower, "antigravity") ->
        antigravity_envelope(prompt)

      true ->
        [prompt]
    end
  end

  # Claude takes system prompt directly without wrapping
  defp claude_wrapper(prompt), do: [prompt]

  # Antigravity models use XML envelope
  defp antigravity_envelope(prompt) do
    ["<antigravity>\n#{prompt}\n</antigravity>"]
  end
end
