defmodule Mana.Models.Settings do
  @moduledoc """
  Model configuration based on model name prefix.

  This module provides intelligent model configuration based on the model name.
  It determines the appropriate provider, token limits, temperature, and
  capability flags (tools, vision) automatically.

  ## Usage

      settings = Mana.Models.Settings.make("claude-3-sonnet-20240229")
      # => %Mana.Models.Settings{
      #      provider: :anthropic,
      #      model_name: "claude-3-sonnet-20240229",
      #      max_tokens: 4096,
      #      temperature: 0.7,
      #      supports_tools: true,
      #      supports_vision: true
      #    }

  ## Supported Model Prefixes

  - `claude-*` → Anthropic provider
  - `gpt-*` → OpenAI provider
  - `ollama/*` → Ollama provider
  - Other models → Default settings (OpenAI-compatible)
  """

  defstruct [
    :provider,
    :model_name,
    :max_tokens,
    :temperature,
    :supports_tools,
    :supports_vision
  ]

  @type t :: %__MODULE__{
          provider: atom(),
          model_name: String.t(),
          max_tokens: integer(),
          temperature: float(),
          supports_tools: boolean(),
          supports_vision: boolean()
        }

  @default_max_tokens 4096
  @default_temperature 0.7

  @doc """
  Creates model settings based on the model name.

  Automatically detects the provider based on model name prefix and
  configures appropriate defaults for capabilities.

  ## Examples

      iex> Mana.Models.Settings.make("claude-3-sonnet-20240229")
      %Mana.Models.Settings{provider: :anthropic, ...}

      iex> Mana.Models.Settings.make("gpt-4")
      %Mana.Models.Settings{provider: :openai, ...}

      iex> Mana.Models.Settings.make("ollama/llama3.2")
      %Mana.Models.Settings{provider: :ollama, ...}
  """
  @spec make(String.t()) :: t()
  def make(model_name) when is_binary(model_name) do
    cond do
      String.starts_with?(model_name, "claude") ->
        anthropic_settings(model_name)

      String.starts_with?(model_name, "gpt") ->
        openai_settings(model_name)

      String.starts_with?(model_name, "ollama/") ->
        ollama_settings(model_name)

      true ->
        default_settings(model_name)
    end
  end

  @doc """
  Returns the provider module for the given settings.

  ## Examples

      iex> settings = Mana.Models.Settings.make("gpt-4")
      iex> Mana.Models.Settings.provider_module(settings)
      Mana.Models.Providers.OpenAI
  """
  @spec provider_module(t()) :: module()
  def provider_module(%__MODULE__{provider: :anthropic}), do: Mana.Models.Providers.Anthropic
  def provider_module(%__MODULE__{provider: :openai}), do: Mana.Models.Providers.OpenAI
  def provider_module(%__MODULE__{provider: :ollama}), do: Mana.Models.Providers.Ollama
  def provider_module(%__MODULE__{provider: _}), do: Mana.Models.Providers.OpenAICompatible

  # Private settings generators

  defp anthropic_settings(name) do
    %__MODULE__{
      provider: :anthropic,
      model_name: name,
      max_tokens: get_max_tokens_for_model(name, :anthropic),
      temperature: @default_temperature,
      supports_tools: anthropic_supports_tools?(name),
      supports_vision: anthropic_supports_vision?(name)
    }
  end

  defp openai_settings(name) do
    %__MODULE__{
      provider: :openai,
      model_name: name,
      max_tokens: get_max_tokens_for_model(name, :openai),
      temperature: @default_temperature,
      supports_tools: openai_supports_tools?(name),
      supports_vision: openai_supports_vision?(name)
    }
  end

  defp ollama_settings(name) do
    %__MODULE__{
      provider: :ollama,
      model_name: name,
      max_tokens: @default_max_tokens,
      temperature: @default_temperature,
      supports_tools: true,
      supports_vision: false
    }
  end

  defp default_settings(name) do
    %__MODULE__{
      provider: :openai_compatible,
      model_name: name,
      max_tokens: @default_max_tokens,
      temperature: @default_temperature,
      supports_tools: false,
      supports_vision: false
    }
  end

  # Capability detection

  defp anthropic_supports_tools?(name) do
    # Claude 3+ supports tools
    String.starts_with?(name, "claude-3") or
      String.starts_with?(name, "claude-2.1")
  end

  defp anthropic_supports_vision?(name) do
    # Claude 3 Sonnet and Opus support vision
    String.contains?(name, "sonnet") or
      String.contains?(name, "opus") or
      String.contains?(name, "haiku") or
      String.starts_with?(name, "claude-3")
  end

  defp openai_supports_tools?(name) do
    # GPT-4 and GPT-3.5-turbo support tools
    String.starts_with?(name, "gpt-4") or
      String.starts_with?(name, "gpt-3.5-turbo")
  end

  defp openai_supports_vision?(name) do
    # Vision models contain "vision" in the name
    String.contains?(name, "vision")
  end

  # Max tokens detection

  defp get_max_tokens_for_model(name, :anthropic) do
    cond do
      String.contains?(name, "opus") -> 128_000
      String.contains?(name, "sonnet") -> 128_000
      String.contains?(name, "haiku") -> 48_000
      true -> @default_max_tokens
    end
  end

  defp get_max_tokens_for_model(name, :openai) do
    cond do
      String.starts_with?(name, "gpt-4o") -> 128_000
      String.starts_with?(name, "gpt-4-turbo") -> 128_000
      String.starts_with?(name, "gpt-4-32k") -> 32_768
      String.starts_with?(name, "gpt-4") -> 8_192
      String.starts_with?(name, "gpt-3.5-turbo-16k") -> 16_384
      String.starts_with?(name, "gpt-3.5-turbo") -> 4_096
      true -> @default_max_tokens
    end
  end

  defp get_max_tokens_for_model(_name, _provider) do
    @default_max_tokens
  end
end
