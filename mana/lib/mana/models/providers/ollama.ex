defmodule Mana.Models.Providers.Ollama do
  @moduledoc """
  Local Ollama provider implementation.

  Uses Ollama's OpenAI-compatible API endpoint at `http://localhost:11434`.
  Delegates to `Mana.Models.Providers.OpenAICompatible` with the Ollama base URL.

  Note: Ollama's API key is optional for local deployments.

  ## Configuration

  The provider accepts these options:
  - `:base_url` - Override the default Ollama URL (default: "http://localhost:11434/v1")
  - `:api_key` - Optional API key for authenticated Ollama instances
  - All other standard completion options

  ## Model Names

  Ollama models are referenced without the "ollama/" prefix when making requests:

  - "llama3.2" → Ollama's llama3.2 model
  - "mistral" → Ollama's mistral model
  - "codellama" → Ollama's codellama model
  """

  @behaviour Mana.Models.Provider

  alias Mana.Models.Providers.OpenAICompatible

  @default_base_url "http://localhost:11434/v1"

  @impl true
  def provider_id, do: "ollama"

  @impl true
  def validate_config(config) do
    base_url = config[:base_url] || @default_base_url

    if is_binary(base_url) and base_url != "" do
      :ok
    else
      {:error, "Missing base_url"}
    end
  end

  @impl true
  def complete(messages, model, opts \\ []) do
    base_url = Keyword.get(opts, :base_url, @default_base_url)

    # Strip "ollama/" prefix from model name if present
    clean_model = strip_ollama_prefix(model)

    # Delegate to OpenAICompatible with Ollama base URL
    # Ollama doesn't require an API key, but OpenAI provider validates it,
    # so we pass a dummy key that won't be used
    opts =
      opts
      |> Keyword.put(:base_url, base_url)
      |> Keyword.put_new(:api_key, "not-needed")

    OpenAICompatible.complete(messages, clean_model, opts)
  end

  @impl true
  def stream(messages, model, opts \\ []) do
    base_url = Keyword.get(opts, :base_url, @default_base_url)

    # Strip "ollama/" prefix from model name if present
    clean_model = strip_ollama_prefix(model)

    # Delegate to OpenAICompatible with Ollama base URL
    # Ollama doesn't require an API key, but OpenAI provider validates it,
    # so we pass a dummy key that won't be used
    opts =
      opts
      |> Keyword.put(:base_url, base_url)
      |> Keyword.put_new(:api_key, "not-needed")

    OpenAICompatible.stream(messages, clean_model, opts)
  end

  # Helper functions

  defp strip_ollama_prefix("ollama/" <> model), do: model
  defp strip_ollama_prefix(model), do: model
end
