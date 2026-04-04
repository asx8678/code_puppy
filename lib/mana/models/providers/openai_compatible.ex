defmodule Mana.Models.Providers.OpenAICompatible do
  @moduledoc """
  Generic provider for OpenAI-compatible APIs.

  Supports any API that implements the OpenAI chat completions interface,
  including Cerebras, Groq, Together, and other compatible services.

  Configuration:
  - `:base_url` - The API base URL (required)
  - `:api_key` - The API key (optional, falls back to Config.api_key/1)
  - All other options passed through to underlying provider

  ## Examples

      # Groq
      Mana.Models.Settings.make("llama-3.1-70b-versatile")
      |> Map.put(:base_url, "https://api.groq.com/openai/v1")

      # Cerebras
      Mana.Models.Settings.make("llama3.1-70b")
      |> Map.put(:base_url, "https://api.cerebras.ai/v1")
  """

  @behaviour Mana.Models.Provider

  alias Mana.Models.Providers.OpenAI

  @impl true
  def provider_id, do: "openai_compatible"

  @impl true
  def validate_config(config) do
    base_url = config[:base_url]

    cond do
      is_nil(base_url) or base_url == "" ->
        {:error, "Missing base_url"}

      not is_binary(base_url) ->
        {:error, "base_url must be a string"}

      true ->
        # Validate API key through OpenAI provider
        OpenAI.validate_config(config)
    end
  end

  @impl true
  def complete(messages, model, opts \\ []) do
    base_url = get_base_url(opts)

    case validate_config(%{base_url: base_url, api_key: get_api_key(opts)}) do
      :ok ->
        # Delegate to OpenAI provider with custom base_url
        opts = Keyword.put(opts, :base_url, base_url)
        OpenAI.complete(messages, model, opts)

      error ->
        error
    end
  end

  @impl true
  def stream(messages, model, opts \\ []) do
    base_url = get_base_url(opts)

    case validate_config(%{base_url: base_url, api_key: get_api_key(opts)}) do
      :ok ->
        # Delegate to OpenAI provider with custom base_url
        opts = Keyword.put(opts, :base_url, base_url)
        OpenAI.stream(messages, model, opts)

      error ->
        Stream.resource(
          fn -> error end,
          fn
            nil -> {:halt, nil}
            {:error, _reason} = err -> {[err], nil}
            err -> {[{:error, err}], nil}
          end,
          fn _ -> :ok end
        )
    end
  end

  # Helper functions

  defp get_base_url(opts) do
    Keyword.get(opts, :base_url)
  end

  defp get_api_key(opts) do
    Keyword.get(opts, :api_key)
  end
end
