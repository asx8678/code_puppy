defmodule Mana.Config do
  @moduledoc """
  Configuration management module with type-safe accessors.

  Provides macro-generated accessor functions for Mana configuration
  with type validation and environment variable integration.

  ## Configuration Keys

  The following configuration keys are supported:

  - `:yolo_mode` - Boolean, default: `false`
  - `:streaming_enabled` - Boolean, default: `true`
  - `:global_model_name` - String, default: `"gpt-4"`
  - `:temperature` - Float, default: `0.7`
  - `:max_tokens` - Integer, default: `4096`
  - `:log_level` - String, default: `"info"`

  ## Usage

      # Boolean accessors (with ? suffix)
      Mana.Config.yolo_mode?()
      Mana.Config.streaming_enabled?()

      # Value accessors
      Mana.Config.global_model_name()
      Mana.Config.temperature()
      Mana.Config.max_tokens()
      Mana.Config.log_level()

      # API key lookup from environment
      Mana.Config.api_key("openai")  # Checks OPENAI_API_KEY

  ## Custom Configuration

  You can add custom configuration by creating your own module:

      defmodule MyApp.Config do
        use Mana.Config.Schema,
          keys: %{
            custom_setting: %{default: "value", type: :string},
            feature_flag: %{default: false, type: :boolean}
          }
      end
  """

  alias Mana.Config.Store

  @config_keys %{
    yolo_mode: %{default: false, type: :boolean},
    streaming_enabled: %{default: true, type: :boolean},
    global_model_name: %{default: "gpt-4", type: :string},
    temperature: %{default: 0.7, type: :float},
    max_tokens: %{default: 4096, type: :integer},
    log_level: %{default: "info", type: :string}
  }

  # API Key Environment Variable Mappings
  @api_key_env_vars %{
    "openai" => "OPENAI_API_KEY",
    "anthropic" => "ANTHROPIC_API_KEY",
    "gemini" => "GEMINI_API_KEY",
    "groq" => "GROQ_API_KEY",
    "ollama" => "OLLAMA_API_KEY",
    "cohere" => "COHERE_API_KEY"
  }

  @doc """
  Returns the full configuration schema.
  """
  @spec config_keys() :: map()
  def config_keys, do: @config_keys

  @doc """
  Returns the configuration value for a key, or the default if not set.

  This is a convenience function that can be used when you need
  dynamic key access rather than the generated accessor functions.
  """
  @spec get(atom(), any()) :: any()
  def get(key, default \\ nil) do
    Store.get(key, default || get_default(key))
  end

  @doc """
  Sets a configuration value.

  The value will be persisted to disk asynchronously.
  """
  @spec put(atom(), any()) :: :ok
  def put(key, value) do
    Store.put(key, value)
  end

  @doc """
  Gets an API key from environment variables.

  Supports the following providers:
  - `"openai"` → `OPENAI_API_KEY`
  - `"anthropic"` → `ANTHROPIC_API_KEY`
  - `"gemini"` → `GEMINI_API_KEY`
  - `"groq"` → `GROQ_API_KEY`
  - `"ollama"` → `OLLAMA_API_KEY`
  - `"cohere"` → `COHERE_API_KEY`

  Returns `nil` if the key is not found.
  """
  @spec api_key(String.t()) :: String.t() | nil
  def api_key(provider) when is_binary(provider) do
    provider_lower = String.downcase(provider)

    case Map.get(@api_key_env_vars, provider_lower) do
      nil ->
        nil

      env_var ->
        case System.get_env(env_var) do
          nil -> nil
          "" -> nil
          key -> key
        end
    end
  end

  @doc """
  Returns a map of all configured API keys.

  Only includes keys that are set in the environment.
  """
  @spec api_keys() :: %{optional(String.t()) => String.t()}
  def api_keys do
    @api_key_env_vars
    |> Enum.map(fn {provider, env_var} ->
      case System.get_env(env_var) do
        nil -> nil
        "" -> nil
        key -> {provider, key}
      end
    end)
    |> Enum.reject(&is_nil/1)
    |> Map.new()
  end

  # Generate accessor functions for each config key

  @doc """
  Returns whether yolo mode is enabled.

  Default: `false`
  """
  @spec yolo_mode?() :: boolean()
  def yolo_mode?, do: Store.get(:yolo_mode, @config_keys.yolo_mode.default)

  @doc """
  Returns whether streaming is enabled.

  Default: `true`
  """
  @spec streaming_enabled?() :: boolean()
  def streaming_enabled?, do: Store.get(:streaming_enabled, @config_keys.streaming_enabled.default)

  @doc """
  Returns the global model name.

  Default: `"gpt-4"`
  """
  @spec global_model_name() :: String.t()
  def global_model_name, do: Store.get(:global_model_name, @config_keys.global_model_name.default)

  @doc """
  Returns the temperature setting.

  Default: `0.7`
  """
  @spec temperature() :: float()
  def temperature, do: Store.get(:temperature, @config_keys.temperature.default)

  @doc """
  Returns the max tokens setting.

  Default: `4096`
  """
  @spec max_tokens() :: integer()
  def max_tokens, do: Store.get(:max_tokens, @config_keys.max_tokens.default)

  @doc """
  Returns the log level setting.

  Default: `"info"`
  """
  @spec log_level() :: String.t()
  def log_level, do: Store.get(:log_level, @config_keys.log_level.default)

  # Private helper functions

  defp get_default(key) do
    case Map.get(@config_keys, key) do
      %{default: default} -> default
      nil -> nil
    end
  end

  # Module for creating custom config schemas
  defmodule Schema do
    @moduledoc """
    Schema generator for custom configuration modules.

    This module provides a macro for defining your own configuration
    schemas with type-safe accessors.

    ## Example

        defmodule MyApp.Config do
          use Mana.Config.Schema,
            keys: %{
              api_timeout: %{default: 30_000, type: :integer},
              retry_count: %{default: 3, type: :integer},
              enable_caching: %{default: true, type: :boolean}
            }
        end

    This will generate:

    - `MyApp.Config.api_timeout/0`
    - `MyApp.Config.retry_count/0`
    - `MyApp.Config.enable_caching?/0` (note the `?` suffix for booleans)
    """

    alias Mana.Config.Store

    defmacro __using__(opts) do
      # Evaluate the keys option to get the actual map
      {keys, _} =
        opts
        |> Keyword.get(:keys, %{})
        |> Code.eval_quoted()

      # Pre-process keys outside the quote
      boolean_keys =
        Enum.filter(keys, fn {_key, spec} -> Map.get(spec, :type) == :boolean end)

      value_keys =
        Enum.filter(keys, fn {_key, spec} -> Map.get(spec, :type) != :boolean end)

      boolean_accessors =
        Enum.map(boolean_keys, fn {key, spec} ->
          default = Map.get(spec, :default)

          quote do
            @doc """
            Returns the value of `#{unquote(key)}`.

            Default: `#{inspect(unquote(default))}`
            """
            @spec unquote(:"#{key}?")() :: boolean()
            def unquote(:"#{key}?")() do
              Store.get(unquote(key), unquote(default))
            end
          end
        end)

      value_accessors =
        Enum.map(value_keys, fn {key, spec} ->
          default = Map.get(spec, :default)
          type = Map.get(spec, :type)

          quote do
            @doc """
            Returns the value of `#{unquote(key)}`.

            Default: `#{inspect(unquote(default))}`
            """
            @spec unquote(key)() :: unquote(type_spec(type))
            def unquote(key)() do
              Store.get(unquote(key), unquote(default))
            end
          end
        end)

      quote do
        import Mana.Config.Schema
        alias Mana.Config.Store

        @config_keys unquote(Macro.escape(keys))

        @doc """
        Returns the full configuration schema.
        """
        @spec config_keys() :: map()
        def config_keys, do: @config_keys

        unquote(boolean_accessors)
        unquote(value_accessors)
      end
    end

    defp type_spec(:boolean), do: quote(do: boolean())
    defp type_spec(:string), do: quote(do: String.t())
    defp type_spec(:integer), do: quote(do: integer())
    defp type_spec(:float), do: quote(do: float())
    defp type_spec(:atom), do: quote(do: atom())
    defp type_spec(:map), do: quote(do: map())
    defp type_spec(:list), do: quote(do: list())
    defp type_spec(_), do: quote(do: any())
  end
end
