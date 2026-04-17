defmodule CodePuppyControl.ModelsDevParser.Registry do
  @moduledoc """
  Registry for managing models and providers from models.dev API.

  Fetches data from the live models.dev API first, falling back to a bundled
  JSON file if the API is unavailable.
  """

  use GenServer

  require Logger

  alias CodePuppyControl.HttpClient
  alias CodePuppyControl.ModelsDevParser.ProviderInfo
  alias CodePuppyControl.ModelsDevParser.ModelInfo

  # Module constants (redefined here for visibility)
  @models_dev_api_url "https://models.dev/api.json"
  @bundled_json_filename "models_dev_api.json"
  @cache_ttl_seconds 300

  @provider_type_map %{
    "anthropic" => "anthropic",
    "openai" => "openai",
    "google" => "gemini",
    "deepseek" => "deepseek",
    "ollama" => "ollama",
    "groq" => "groq",
    "cohere" => "cohere",
    "mistral" => "mistral"
  }

  defstruct [
    :providers,
    :models,
    :data_source,
    :cached_data,
    :cache_time,
    :json_path
  ]

  @type t :: %__MODULE__{
          providers: %{String.t() => ProviderInfo.t()},
          models: %{String.t() => ModelInfo.t()},
          data_source: String.t(),
          cached_data: map() | nil,
          cache_time: non_neg_integer() | nil,
          json_path: String.t() | nil
        }

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the registry (synchronous, loads from file only).

  For async loading with live API fetch, use `start_link/1` or `new_async/0`.

  Options:
  - `:json_path` - Optional path to a local JSON file (for testing/offline use)
  - `:skip_live_api` - If true, skip live API fetch (default for sync usage)
  - `:name` - GenServer name (default: __MODULE__)
  """
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Creates a new registry instance synchronously (file loading only).
  """
  @spec new(Keyword.t()) :: {:ok, pid()} | {:error, term()}
  def new(opts \\ []) do
    start_link(opts)
  end

  @doc """
  Creates a new registry instance asynchronously with API fetching.
  """
  @spec new_async(Keyword.t()) :: {:ok, pid()} | {:error, term()}
  def new_async(opts \\ []) do
    # For async, we'll let the GenServer handle the async load in init
    opts = Keyword.put(opts, :async_load, true)
    start_link(opts)
  end

  @doc "Get all providers, sorted by name."
  @spec get_providers(pid() | atom()) :: [ProviderInfo.t()]
  def get_providers(pid \\ __MODULE__) do
    GenServer.call(pid, :get_providers)
  end

  @doc "Get a specific provider by ID."
  @spec get_provider(pid() | atom(), String.t()) :: ProviderInfo.t() | nil
  def get_provider(pid \\ __MODULE__, provider_id) do
    GenServer.call(pid, {:get_provider, provider_id})
  end

  @doc "Get models, optionally filtered by provider."
  @spec get_models(pid() | atom(), String.t() | nil) :: [ModelInfo.t()]
  def get_models(pid \\ __MODULE__, provider_id \\ nil) do
    GenServer.call(pid, {:get_models, provider_id})
  end

  @doc "Get a specific model."
  @spec get_model(pid() | atom(), String.t(), String.t()) :: ModelInfo.t() | nil
  def get_model(pid \\ __MODULE__, provider_id, model_id) do
    GenServer.call(pid, {:get_model, provider_id, model_id})
  end

  @doc """
  Search models by name/query and filter by capabilities.

  Options:
  - `:query` - Search string (case-insensitive)
  - `:capability_filters` - Map of capability names to required values
  """
  @spec search_models(pid() | atom(), Keyword.t()) :: [ModelInfo.t()]
  def search_models(pid \\ __MODULE__, opts \\ []) do
    GenServer.call(pid, {:search_models, opts})
  end

  @doc "Filter models by cost constraints."
  @spec filter_by_cost(
          pid() | atom(),
          [ModelInfo.t()],
          number() | nil,
          number() | nil
        ) :: [ModelInfo.t()]
  def filter_by_cost(pid \\ __MODULE__, models, max_input_cost \\ nil, max_output_cost \\ nil) do
    GenServer.call(pid, {:filter_by_cost, models, max_input_cost, max_output_cost})
  end

  @doc "Filter models by minimum context length."
  @spec filter_by_context(pid() | atom(), [ModelInfo.t()], non_neg_integer()) ::
          [ModelInfo.t()]
  def filter_by_context(pid \\ __MODULE__, models, min_context_length) do
    GenServer.call(pid, {:filter_by_context, models, min_context_length})
  end

  @doc "Convert a model to Code Puppy configuration format."
  @spec to_config(pid() | atom(), ModelInfo.t()) :: map()
  def to_config(pid \\ __MODULE__, %ModelInfo{} = model) do
    GenServer.call(pid, {:to_config, model})
  end

  @doc "Get data source information."
  @spec data_source(pid() | atom()) :: String.t()
  def data_source(pid \\ __MODULE__) do
    GenServer.call(pid, :data_source)
  end

  @doc "Refresh data from API (bypasses cache)."
  @spec refresh(pid() | atom()) :: :ok | {:error, term()}
  def refresh(pid \\ __MODULE__) do
    GenServer.call(pid, :refresh)
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(opts) do
    json_path = Keyword.get(opts, :json_path)
    async_load = Keyword.get(opts, :async_load, false)

    state = %__MODULE__{
      providers: %{},
      models: %{},
      data_source: "unknown",
      cached_data: nil,
      cache_time: nil,
      json_path: json_path
    }

    if async_load do
      # Schedule async load
      send(self(), :async_load)
      {:ok, state}
    else
      # Synchronous load
      case load_data_sync(state) do
        {:ok, new_state} -> {:ok, new_state}
        {:error, reason} -> {:stop, reason}
      end
    end
  end

  @impl true
  def handle_info(:async_load, state) do
    case load_data_async(state) do
      {:ok, new_state} ->
        Logger.info("ModelsDev registry loaded: #{new_state.data_source}")
        {:noreply, new_state}

      {:error, reason} ->
        Logger.error("Failed to load ModelsDev registry: #{inspect(reason)}")
        {:stop, reason, state}
    end
  end

  @impl true
  def handle_call(:get_providers, _from, state) do
    providers =
      state.providers
      |> Map.values()
      |> Enum.sort_by(&String.downcase(&1.name))

    {:reply, providers, state}
  end

  @impl true
  def handle_call({:get_provider, provider_id}, _from, state) do
    {:reply, Map.get(state.providers, provider_id), state}
  end

  @impl true
  def handle_call({:get_models, provider_id}, _from, state) do
    models =
      if provider_id do
        prefix = "#{provider_id}::"

        state.models
        |> Enum.filter(fn {key, _} -> String.starts_with?(key, prefix) end)
        |> Enum.map(fn {_, model} -> model end)
      else
        Map.values(state.models)
      end
      |> Enum.sort_by(&String.downcase(&1.name))

    {:reply, models, state}
  end

  @impl true
  def handle_call({:get_model, provider_id, model_id}, _from, state) do
    full_id = "#{provider_id}::#{model_id}"
    {:reply, Map.get(state.models, full_id), state}
  end

  @impl true
  def handle_call({:search_models, opts}, _from, state) do
    query = Keyword.get(opts, :query)
    capability_filters = Keyword.get(opts, :capability_filters, %{})

    models =
      state.models
      |> Map.values()
      |> apply_query_filter(query)
      |> apply_capability_filters(capability_filters)
      |> Enum.sort_by(&String.downcase(&1.name))

    {:reply, models, state}
  end

  @impl true
  def handle_call({:filter_by_cost, models, max_input_cost, max_output_cost}, _from, state) do
    filtered =
      models
      |> apply_max_input_cost(max_input_cost)
      |> apply_max_output_cost(max_output_cost)

    {:reply, filtered, state}
  end

  @impl true
  def handle_call({:filter_by_context, models, min_context_length}, _from, state) do
    filtered = Enum.filter(models, &(&1.context_length >= min_context_length))
    {:reply, filtered, state}
  end

  @impl true
  def handle_call({:to_config, model}, _from, state) do
    config = build_config(model, state.providers[model.provider_id])
    {:reply, config, state}
  end

  @impl true
  def handle_call(:data_source, _from, state) do
    {:reply, state.data_source, state}
  end

  @impl true
  def handle_call(:refresh, _from, state) do
    # Clear cache and reload
    new_state = %{state | cached_data: nil, cache_time: nil}

    case load_data_async(new_state) do
      {:ok, loaded_state} -> {:reply, :ok, loaded_state}
      {:error, reason} -> {:reply, {:error, reason}, state}
    end
  end

  # ============================================================================
  # Private Functions - Data Loading
  # ============================================================================

  defp load_data_sync(state) do
    cond do
      state.json_path != nil ->
        load_from_file(state, state.json_path)

      true ->
        # Fall back to bundled JSON (no live API in sync mode)
        bundled_path = get_bundled_json_path()

        if File.exists?(bundled_path) do
          load_from_file(state, bundled_path)
        else
          {:error, "No data source available: bundled file not found at #{bundled_path}"}
        end
    end
  end

  # BUG FIX: Normalized return type to 2-tuple {:ok, new_state}
  defp load_data_async(state) do
    cond do
      state.json_path != nil ->
        load_from_file(state, state.json_path)

      true ->
        # Try live API first
        case fetch_from_api(state) do
          {:ok, data} ->
            new_state = %{state | data_source: "live:models.dev"}
            {:ok, parse_data(new_state, data)}

          {:error, _} ->
            # Fall back to bundled
            bundled_path = get_bundled_json_path()

            if File.exists?(bundled_path) do
              load_from_file(state, bundled_path)
            else
              {:error, "No data source available: API failed and bundled file not found"}
            end
        end
    end
  end

  defp load_from_file(state, path) do
    case File.read(path) do
      {:ok, content} ->
        case Jason.decode(content) do
          {:ok, data} ->
            data_source =
              if path == get_bundled_json_path() do
                "bundled:#{@bundled_json_filename}"
              else
                "file:#{path}"
              end

            new_state = %{state | data_source: data_source}
            {:ok, parse_data(new_state, data)}

          {:error, reason} ->
            {:error, "Invalid JSON in #{path}: #{inspect(reason)}"}
        end

      {:error, reason} ->
        {:error, "Failed to read #{path}: #{inspect(reason)}"}
    end
  end

  defp fetch_from_api(%{cached_data: data, cache_time: time} = state)
       when not is_nil(data) and not is_nil(time) do
    now = System.monotonic_time(:second)
    age = now - time

    if age < @cache_ttl_seconds do
      Logger.info("Using cached models data (#{age}s old)")
      {:ok, data}
    else
      do_fetch_from_api(state)
    end
  end

  defp fetch_from_api(state) do
    do_fetch_from_api(state)
  end

  # BUG FIX: Now returns 2-tuple {:ok, data} to match expected return type
  defp do_fetch_from_api(state) do
    case HttpClient.get(@models_dev_api_url, timeout: 10_000) do
      {:ok, %{status: 200, body: body}} ->
        case Jason.decode(body) do
          {:ok, data} when is_map(data) and map_size(data) > 0 ->
            now = System.monotonic_time(:second)
            # Update cache in state but return just the data
            _new_state = %{state | cached_data: data, cache_time: now}
            {:ok, data}

          _ ->
            {:error, :invalid_response}
        end

      {:ok, %{status: status}} ->
        Logger.warning("models.dev API returned #{status}, using fallback")
        {:error, {:http_error, status}}

      {:error, reason} ->
        Logger.warning("Failed to fetch from models.dev API: #{inspect(reason)}")
        {:error, reason}
    end
  end

  defp get_bundled_json_path do
    # Look for bundled JSON in priv directory relative to this module
    priv_dir = :code.priv_dir(:code_puppy_control)
    Path.join(priv_dir, @bundled_json_filename)
  end

  # ============================================================================
  # Private Functions - Data Parsing
  # ============================================================================

  defp parse_data(state, data) when is_map(data) do
    providers = %{}
    models = %{}

    {providers, models} =
      Enum.reduce(data, {providers, models}, fn {provider_id, provider_data}, {ps, ms} ->
        try do
          provider = parse_provider(provider_id, provider_data)

          # Parse models nested under the provider
          models_data = Map.get(provider_data, "models", %{})

          ms =
            Enum.reduce(models_data, ms, fn {model_id, model_data}, acc ->
              try do
                model = parse_model(provider_id, model_id, model_data)
                Map.put(acc, ModelInfo.full_id(model), model)
              rescue
                e ->
                  Logger.warning(
                    "Skipping malformed model #{provider_id}::#{model_id}: #{inspect(e)}"
                  )

                  acc
              end
            end)

          {Map.put(ps, provider_id, provider), ms}
        rescue
          e ->
            Logger.warning("Skipping malformed provider #{provider_id}: #{inspect(e)}")
            {ps, ms}
        end
      end)

    Logger.info("Loaded #{map_size(providers)} providers and #{map_size(models)} models")

    %{state | providers: providers, models: models}
  end

  defp parse_provider(provider_id, data) do
    # Required fields
    name = Map.get(data, "name")
    env = Map.get(data, "env")

    if is_nil(name) or is_nil(env) do
      raise "Missing required provider fields: name or env"
    end

    %ProviderInfo{
      id: provider_id,
      name: name,
      env: env,
      api: Map.get(data, "api", ""),
      npm: Map.get(data, "npm"),
      doc: Map.get(data, "doc"),
      models: Map.get(data, "models", %{})
    }
  end

  defp parse_model(provider_id, model_id, data) do
    name = Map.get(data, "name")

    if is_nil(name) do
      raise "Missing required model field: name"
    end

    # Extract nested data
    cost_data = Map.get(data, "cost", %{})
    limit_data = Map.get(data, "limit", %{})
    modalities = Map.get(data, "modalities", %{})

    context_length = Map.get(limit_data, "context", 0)
    max_output = Map.get(limit_data, "output", 0)

    # Validate numeric fields
    if context_length < 0 do
      raise "Context length cannot be negative"
    end

    if max_output < 0 do
      raise "Max output cannot be negative"
    end

    %ModelInfo{
      provider_id: provider_id,
      model_id: model_id,
      name: name,
      attachment: Map.get(data, "attachment", false),
      reasoning: Map.get(data, "reasoning", false),
      tool_call: Map.get(data, "tool_call", false),
      temperature: Map.get(data, "temperature", true),
      structured_output: Map.get(data, "structured_output", false),
      cost_input: Map.get(cost_data, "input"),
      cost_output: Map.get(cost_data, "output"),
      cost_cache_read: Map.get(cost_data, "cache_read"),
      context_length: context_length,
      max_output: max_output,
      input_modalities: Map.get(modalities, "input", []),
      output_modalities: Map.get(modalities, "output", []),
      knowledge: Map.get(data, "knowledge"),
      release_date: Map.get(data, "release_date"),
      last_updated: Map.get(data, "last_updated"),
      open_weights: Map.get(data, "open_weights", false)
    }
  end

  # ============================================================================
  # Private Functions - Filtering
  # ============================================================================

  defp apply_query_filter(models, nil), do: models
  defp apply_query_filter(models, ""), do: models

  defp apply_query_filter(models, query) do
    query_lower = String.downcase(query)

    Enum.filter(models, fn model ->
      String.contains?(String.downcase(model.name), query_lower) or
        String.contains?(String.downcase(model.model_id), query_lower)
    end)
  end

  defp apply_capability_filters(models, filters) when map_size(filters) == 0, do: models

  # BUG FIX: Use String.to_existing_atom with rescue instead of String.to_atom
  defp apply_capability_filters(models, filters) do
    Enum.reduce(filters, models, fn {capability, required}, acc ->
      Enum.filter(acc, fn model ->
        if is_boolean(required) do
          ModelInfo.supports_capability?(model, capability) == required
        else
          # Try to get the field, but safely
          atom_key = safe_to_atom(capability)
          if atom_key, do: Map.get(model, atom_key) == required, else: false
        end
      end)
    end)
  end

  # Safely convert string to existing atom, returns nil if not found
  defp safe_to_atom(string) when is_binary(string) do
    String.to_existing_atom(string)
  rescue
    ArgumentError -> nil
  end

  defp safe_to_atom(atom) when is_atom(atom), do: atom
  defp safe_to_atom(_), do: nil

  defp apply_max_input_cost(models, nil), do: models

  defp apply_max_input_cost(models, max_cost) do
    Enum.filter(models, fn m ->
      m.cost_input != nil and m.cost_input <= max_cost
    end)
  end

  defp apply_max_output_cost(models, nil), do: models

  defp apply_max_output_cost(models, max_cost) do
    Enum.filter(models, fn m ->
      m.cost_output != nil and m.cost_output <= max_cost
    end)
  end

  # ============================================================================
  # Private Functions - Config Conversion
  # ============================================================================

  defp build_config(model, provider) do
    provider_type = Map.get(@provider_type_map, provider.id, provider.id)

    # Basic configuration
    config = %{
      "type" => provider_type,
      "model" => model.model_id,
      "enabled" => true,
      "provider_id" => provider.id,
      "env_vars" => provider.env
    }

    # Add optional fields
    config = if provider.api, do: Map.put(config, "api_url", provider.api), else: config
    config = if provider.npm, do: Map.put(config, "npm_package", provider.npm), else: config

    # Add cost information
    config =
      if model.cost_input,
        do: Map.put(config, "input_cost_per_token", model.cost_input),
        else: config

    config =
      if model.cost_output,
        do: Map.put(config, "output_cost_per_token", model.cost_output),
        else: config

    config =
      if model.cost_cache_read,
        do: Map.put(config, "cache_read_cost_per_token", model.cost_cache_read),
        else: config

    # Add limits
    config =
      if model.context_length > 0,
        do: Map.put(config, "max_tokens", model.context_length),
        else: config

    config =
      if model.max_output > 0,
        do: Map.put(config, "max_output_tokens", model.max_output),
        else: config

    # Add capabilities
    capabilities = %{
      "attachment" => model.attachment,
      "reasoning" => model.reasoning,
      "tool_call" => model.tool_call,
      "temperature" => model.temperature,
      "structured_output" => model.structured_output
    }

    config = Map.put(config, "capabilities", capabilities)

    # Add modalities
    config =
      if model.input_modalities != [],
        do: Map.put(config, "input_modalities", model.input_modalities),
        else: config

    config =
      if model.output_modalities != [],
        do: Map.put(config, "output_modalities", model.output_modalities),
        else: config

    # Add metadata
    metadata = %{}

    metadata =
      if model.knowledge, do: Map.put(metadata, "knowledge", model.knowledge), else: metadata

    metadata =
      if model.release_date,
        do: Map.put(metadata, "release_date", model.release_date),
        else: metadata

    metadata =
      if model.last_updated,
        do: Map.put(metadata, "last_updated", model.last_updated),
        else: metadata

    metadata = Map.put(metadata, "open_weights", model.open_weights)

    if map_size(metadata) > 0 do
      Map.put(config, "metadata", metadata)
    else
      config
    end
  end
end
