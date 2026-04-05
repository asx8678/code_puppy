defmodule Mana.Models.Registry do
  @moduledoc """
  GenServer for provider dispatch and model configuration management.

  The Registry maintains a mapping of provider IDs to provider modules,
  and model names to model configurations. It provides:

  - Provider dispatch for `complete/3` and `stream/3` operations
  - Model configuration storage and retrieval
  - Plugin callback integration via `:register_model_type`
  - Statistics tracking for dispatches and errors

  ## Usage

      # Start the registry
      Mana.Models.Registry.start_link()

      # Get provider for a model
      {:ok, provider} = Mana.Models.Registry.get_provider("gpt-4")

      # Dispatch completion
      {:ok, response} = Mana.Models.Registry.complete(messages, "gpt-4", opts)

      # List registered models
      models = Mana.Models.Registry.list_models()

  ## Auto-registered Providers

  The following providers are automatically registered on init:

  - `"openai"` → `Mana.Models.Providers.OpenAI`
  - `"anthropic"` → `Mana.Models.Providers.Anthropic`
  - `"openai_compatible"` → `Mana.Models.Providers.OpenAICompatible`
  - `"ollama"` → `Mana.Models.Providers.Ollama`
  - `"claude_code"` → `Mana.OAuth.ClaudeCode`
  - `"chatgpt"` → `Mana.OAuth.ChatGPT`
  - `"antigravity"` → `Mana.OAuth.Antigravity`
  """

  use GenServer

  require Logger

  alias Mana.Models.Settings

  defstruct providers: %{},
            models: %{},
            stats: %{dispatches: 0, errors: 0}

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the Models Registry GenServer.

  ## Options

  - `:name` - The name to register the process under (default: `__MODULE__`)

  ## Examples

      {:ok, pid} = Mana.Models.Registry.start_link()
      {:ok, pid} = Mana.Models.Registry.start_link(name: :my_registry)
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Returns the provider module for a given model name.

  Uses `Mana.Models.Settings.make/1` to determine the provider based on
  the model name prefix, then looks up the registered provider module.

  ## Examples

      {:ok, provider} = Mana.Models.Registry.get_provider("gpt-4")
      # => {:ok, Mana.Models.Providers.OpenAI}

      {:ok, provider} = Mana.Models.Registry.get_provider("claude-3-opus")
      # => {:ok, Mana.Models.Providers.Anthropic}
  """
  @spec get_provider(String.t()) :: {:ok, module()} | {:error, term()}
  def get_provider(model_name) do
    GenServer.call(__MODULE__, {:get_provider, model_name})
  end

  @doc """
  Registers a provider module with the given ID.

  ## Examples

      :ok = Mana.Models.Registry.register_provider("custom", MyApp.CustomProvider)
  """
  @spec register_provider(String.t(), module()) :: :ok
  def register_provider(id, module) do
    GenServer.call(__MODULE__, {:register_provider, id, module})
  end

  @doc """
  Returns the configuration for a specific model.

  ## Examples

      {:ok, config} = Mana.Models.Registry.get_model("gpt-4")
      # => {:ok, %{provider: "openai", max_tokens: 4096, supports_tools: true}}
  """
  @spec get_model(String.t()) :: {:ok, map()} | {:error, :not_found}
  def get_model(name) do
    GenServer.call(__MODULE__, {:get_model, name})
  end

  @doc """
  Registers a model configuration.

  ## Examples

      config = %{provider: "custom", max_tokens: 8192, supports_tools: true}
      :ok = Mana.Models.Registry.register_model("my-model", config)
  """
  @spec register_model(String.t(), map()) :: :ok
  def register_model(name, config) do
    GenServer.call(__MODULE__, {:register_model, name, config})
  end

  @doc """
  Lists all registered models with their configurations.

  ## Examples

      models = Mana.Models.Registry.list_models()
      # => %{"gpt-4" => %{...}, "claude-3-opus" => %{...}}
  """
  @spec list_models() :: %{String.t() => map()}
  def list_models do
    GenServer.call(__MODULE__, :list_models)
  end

  @doc """
  Lists all registered providers.

  ## Examples

      providers = Mana.Models.Registry.list_providers()
      # => %{"openai" => Mana.Models.Providers.OpenAI, ...}
  """
  @spec list_providers() :: %{String.t() => module()}
  def list_providers do
    GenServer.call(__MODULE__, :list_providers)
  end

  @doc """
  Performs a completion request, dispatching to the appropriate provider.

  Automatically determines the provider based on the model name and
  delegates to the provider's `complete/3` function.

  ## Examples

      messages = [%{"role" => "user", "content" => "Hello"}]
      {:ok, response} = Mana.Models.Registry.complete(messages, "gpt-4", temperature: 0.7)
  """
  @spec complete([map()], String.t(), keyword()) :: {:ok, map()} | {:error, term()}
  def complete(messages, model, opts \\ []) do
    GenServer.call(__MODULE__, {:complete, messages, model, opts})
  end

  @doc """
  Performs a streaming completion request, dispatching to the appropriate provider.

  Returns an `Enumerable.t()` that yields stream events from the provider.

  ## Examples

      messages = [%{"role" => "user", "content" => "Hello"}]
      stream = Mana.Models.Registry.stream(messages, "gpt-4")

      Enum.each(stream, fn event ->
        case event do
          {:part_delta, :content, text} -> IO.write(text)
          {:part_end, :done} -> IO.puts("\nDone!")
          _ -> :ok
        end
      end)
  """
  @spec stream([map()], String.t(), keyword()) :: Enumerable.t()
  def stream(messages, model, opts \\ []) do
    GenServer.call(__MODULE__, {:stream, messages, model, opts})
  end

  @doc """
  Returns current registry statistics.

  ## Examples

      stats = Mana.Models.Registry.get_stats()
      # => %{dispatches: 10, errors: 0}
  """
  @spec get_stats() :: map()
  def get_stats do
    GenServer.call(__MODULE__, :get_stats)
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    # Auto-register built-in providers
    providers = %{
      "openai" => Mana.Models.Providers.OpenAI,
      "anthropic" => Mana.Models.Providers.Anthropic,
      "openai_compatible" => Mana.Models.Providers.OpenAICompatible,
      "ollama" => Mana.Models.Providers.Ollama,
      "claude_code" => Mana.OAuth.ClaudeCode,
      "chatgpt" => Mana.OAuth.ChatGPT,
      "antigravity" => Mana.OAuth.Antigravity
    }

    # Load models from JSON config
    models = load_models_from_config()

    # Fire :register_model_type callbacks for plugin models
    models = merge_plugin_models(models)

    {:ok, %__MODULE__{providers: providers, models: models}}
  end

  @impl true
  def handle_call({:get_provider, model_name}, _from, state) do
    settings = Settings.make(model_name)
    provider_id = to_string(settings.provider)

    case Map.get(state.providers, provider_id) do
      nil -> {:reply, {:error, :provider_not_found}, state}
      provider -> {:reply, {:ok, provider}, state}
    end
  end

  @impl true
  def handle_call({:register_provider, id, module}, _from, state) do
    new_providers = Map.put(state.providers, id, module)
    {:reply, :ok, %{state | providers: new_providers}}
  end

  @impl true
  def handle_call({:get_model, name}, _from, state) do
    case Map.get(state.models, name) do
      nil -> {:reply, {:error, :not_found}, state}
      config -> {:reply, {:ok, config}, state}
    end
  end

  @impl true
  def handle_call({:register_model, name, config}, _from, state) do
    new_models = Map.put(state.models, name, config)
    {:reply, :ok, %{state | models: new_models}}
  end

  @impl true
  def handle_call(:list_models, _from, state) do
    {:reply, state.models, state}
  end

  @impl true
  def handle_call(:list_providers, _from, state) do
    {:reply, state.providers, state}
  end

  @impl true
  def handle_call({:complete, messages, model, opts}, _from, state) do
    case get_provider_from_state(state, model) do
      {:ok, provider} ->
        try do
          result = provider.complete(messages, model, opts)

          new_stats =
            case result do
              {:ok, _} -> %{state.stats | dispatches: state.stats.dispatches + 1}
              {:error, _} -> %{state.stats | dispatches: state.stats.dispatches + 1, errors: state.stats.errors + 1}
            end

          {:reply, result, %{state | stats: new_stats}}
        rescue
          e ->
            Logger.error("Provider complete error: #{inspect(e)}")
            new_stats = %{state.stats | dispatches: state.stats.dispatches + 1, errors: state.stats.errors + 1}
            {:reply, {:error, :provider_error}, %{state | stats: new_stats}}
        end

      error ->
        new_stats = %{state.stats | errors: state.stats.errors + 1}
        {:reply, error, %{state | stats: new_stats}}
    end
  end

  @impl true
  def handle_call({:stream, messages, model, opts}, _from, state) do
    case get_provider_from_state(state, model) do
      {:ok, provider} ->
        try do
          result = provider.stream(messages, model, opts)
          new_stats = %{state.stats | dispatches: state.stats.dispatches + 1}
          {:reply, result, %{state | stats: new_stats}}
        rescue
          e ->
            Logger.error("Provider stream error: #{inspect(e)}")
            new_stats = %{state.stats | dispatches: state.stats.dispatches + 1, errors: state.stats.errors + 1}
            {:reply, {:error, :provider_error}, %{state | stats: new_stats}}
        end

      error ->
        new_stats = %{state.stats | errors: state.stats.errors + 1}
        {:reply, error, %{state | stats: new_stats}}
    end
  end

  @impl true
  def handle_call(:get_stats, _from, state) do
    {:reply, state.stats, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp get_provider_from_state(state, model_name) do
    settings = Settings.make(model_name)
    provider_id = to_string(settings.provider)

    case Map.get(state.providers, provider_id) do
      nil -> {:error, :provider_not_found}
      provider -> {:ok, provider}
    end
  end

  defp load_models_from_config do
    # Try to load from priv/models.json, fall back to defaults
    priv_path = Application.app_dir(:mana, "priv/models.json")

    case File.read(priv_path) do
      {:ok, data} ->
        case Jason.decode(data) do
          {:ok, models} when is_map(models) -> models
          _ -> default_models()
        end

      {:error, _} ->
        default_models()
    end
  end

  defp default_models do
    %{
      "claude-opus-4-6" => %{
        "provider" => "anthropic",
        "max_tokens" => 4096,
        "supports_tools" => true,
        "supports_vision" => true
      },
      "claude-sonnet-4-5" => %{
        "provider" => "anthropic",
        "max_tokens" => 4096,
        "supports_tools" => true,
        "supports_vision" => true
      },
      "gpt-4o" => %{
        "provider" => "openai",
        "max_tokens" => 4096,
        "supports_tools" => true,
        "supports_vision" => true
      },
      "gpt-4o-mini" => %{
        "provider" => "openai",
        "max_tokens" => 4096,
        "supports_tools" => true,
        "supports_vision" => false
      }
    }
  end

  defp merge_plugin_models(models) do
    # Try to dispatch to :register_model_type callbacks, but handle case
    # where Callbacks.Registry isn't started yet
    case Mana.Callbacks.dispatch(:register_model_type, []) do
      {:ok, results} when is_list(results) ->
        Enum.reduce(results, models, fn
          %{name: name, config: config}, acc when is_binary(name) and is_map(config) ->
            Map.put(acc, name, config)

          _, acc ->
            acc
        end)

      _ ->
        models
    end
  rescue
    _ -> models
  catch
    :exit, _ -> models
  end
end
