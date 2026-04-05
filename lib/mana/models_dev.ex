defmodule Mana.ModelsDev do
  @moduledoc """
  GenServer client for https://models.dev/api.json with 24h cache.

  This module provides access to the models.dev API, which contains
  comprehensive model information from multiple providers. Data is cached
  locally with automatic refresh every 24 hours.

  ## Features

  - Automatic data fetching from models.dev API
  - 24-hour TTL cache with automatic refresh
  - Bundled fallback data for offline usage
  - Provider and model listing
  - Model search by name/keyword

  ## Usage

      # Start the GenServer
      Mana.ModelsDev.start_link()

      # List all providers
      providers = Mana.ModelsDev.list_providers()

      # List models for a specific provider
      models = Mana.ModelsDev.list_models("anthropic")

      # Search for models
      results = Mana.ModelsDev.search("claude")

      # Get a specific model
      model = Mana.ModelsDev.get_model("claude-opus-4-6")

      # Force refresh from API
      :ok = Mana.ModelsDev.refresh()

  ## Cache Strategy

  1. On init, loads bundled data from `priv/models_dev_api.json`
  2. Schedules automatic refresh after 24 hours
  3. On refresh, fetches from API and updates bundled data
  4. If API fetch fails, keeps existing data
  """

  use GenServer

  require Logger

  @api_url "https://models.dev/api.json"
  @cache_ttl 24 * 60 * 60 * 1000
  @bundled_path "priv/models_dev_api.json"

  defstruct data: %{},
            last_refresh: nil,
            refresh_timer: nil

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the ModelsDev GenServer.

  ## Options

  - `:name` - The name to register the process under (default: `__MODULE__`)

  ## Examples

      {:ok, pid} = Mana.ModelsDev.start_link()
      {:ok, pid} = Mana.ModelsDev.start_link(name: :models_dev)
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Lists all provider IDs from models.dev.

  ## Examples

      providers = Mana.ModelsDev.list_providers()
      # => ["anthropic", "openai", "google", ...]
  """
  @spec list_providers() :: [String.t()]
  def list_providers do
    GenServer.call(__MODULE__, :list_providers)
  end

  @doc """
  Lists all models for a specific provider.

  ## Examples

      models = Mana.ModelsDev.list_models("anthropic")
      # => [%{"name" => "claude-opus-4-6", "context" => 200000}, ...]
  """
  @spec list_models(String.t()) :: [map()]
  def list_models(provider_id) do
    GenServer.call(__MODULE__, {:list_models, provider_id})
  end

  @doc """
  Searches for models by name or keyword.

  The search is case-insensitive and matches partial names.

  ## Examples

      results = Mana.ModelsDev.search("claude")
      # => [%{"name" => "claude-opus-4-6", ...}, ...]

      results = Mana.ModelsDev.search("4o")
      # => [%{"name" => "gpt-4o", ...}, ...]
  """
  @spec search(String.t()) :: [map()]
  def search(query) do
    GenServer.call(__MODULE__, {:search, query})
  end

  @doc """
  Gets a specific model by name.

  Returns the model map if found, or `nil` if not found.

  ## Examples

      model = Mana.ModelsDev.get_model("claude-opus-4-6")
      # => %{"name" => "claude-opus-4-6", "context" => 200000, ...}

      model = Mana.ModelsDev.get_model("unknown-model")
      # => nil
  """
  @spec get_model(String.t()) :: map() | nil
  def get_model(name) do
    GenServer.call(__MODULE__, {:get_model, name})
  end

  @doc """
  Gets the full models.dev data structure.

  Returns the entire data map keyed by provider ID.

  ## Examples

      data = Mana.ModelsDev.get_data()
      # => %{"anthropic" => %{"models" => [...]}, "openai" => %{...}}
  """
  @spec get_data() :: map()
  def get_data do
    GenServer.call(__MODULE__, :get_data)
  end

  @doc """
  Forces a refresh from the models.dev API.

  This will immediately fetch fresh data from the API and update
  the bundled cache file. Returns `:ok` on success or an error
  tuple if the refresh failed.

  ## Examples

      :ok = Mana.ModelsDev.refresh()

      {:error, reason} = Mana.ModelsDev.refresh()
  """
  @spec refresh() :: :ok | {:error, term()}
  def refresh do
    GenServer.call(__MODULE__, :refresh)
  end

  @doc """
  Returns the timestamp of the last successful refresh.

  ## Examples

      last_refresh = Mana.ModelsDev.last_refresh()
      # => ~U[2024-01-15 10:30:00Z]
  """
  @spec last_refresh() :: DateTime.t() | nil
  def last_refresh do
    GenServer.call(__MODULE__, :last_refresh)
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(_opts) do
    # Load bundled data on startup
    data = load_bundled()

    # Schedule first refresh
    timer = Process.send_after(self(), :refresh, @cache_ttl)

    {:ok, %__MODULE__{data: data, last_refresh: DateTime.utc_now(), refresh_timer: timer}}
  end

  @impl true
  def handle_call(:list_providers, _from, state) do
    providers = Map.keys(state.data)
    {:reply, providers, state}
  end

  @impl true
  def handle_call({:list_models, provider_id}, _from, state) do
    models = get_in(state.data, [provider_id, "models"]) || []
    {:reply, models, state}
  end

  @impl true
  def handle_call({:search, query}, _from, state) do
    results = search_in_data(state.data, query)
    {:reply, results, state}
  end

  @impl true
  def handle_call({:get_model, name}, _from, state) do
    result = find_model_in_data(state.data, name)
    {:reply, result, state}
  end

  @impl true
  def handle_call(:get_data, _from, state) do
    {:reply, state.data, state}
  end

  @impl true
  def handle_call(:refresh, _from, state) do
    # Cancel existing timer
    if state.refresh_timer do
      Process.cancel_timer(state.refresh_timer)
    end

    case fetch_from_api() do
      {:ok, data} ->
        save_bundled(data)
        timer = Process.send_after(self(), :refresh, @cache_ttl)

        {:reply, :ok, %{state | data: data, last_refresh: DateTime.utc_now(), refresh_timer: timer}}

      error ->
        # Reschedule timer even on error
        timer = Process.send_after(self(), :refresh, @cache_ttl)
        {:reply, error, %{state | refresh_timer: timer}}
    end
  end

  @impl true
  def handle_call(:last_refresh, _from, state) do
    {:reply, state.last_refresh, state}
  end

  @impl true
  def handle_info(:refresh, state) do
    case fetch_from_api() do
      {:ok, data} ->
        save_bundled(data)
        timer = Process.send_after(self(), :refresh, @cache_ttl)

        {:noreply, %{state | data: data, last_refresh: DateTime.utc_now(), refresh_timer: timer}}

      {:error, reason} ->
        Logger.warning("ModelsDev auto-refresh failed: #{inspect(reason)}")
        # Schedule next refresh attempt
        timer = Process.send_after(self(), :refresh, @cache_ttl)
        {:noreply, %{state | refresh_timer: timer}}
    end
  end

  @impl true
  def handle_info(_msg, state) do
    {:noreply, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp fetch_from_api do
    case Req.get(@api_url) do
      {:ok, %{status: 200, body: body}} ->
        {:ok, body}

      {:ok, %{status: status}} ->
        {:error, "HTTP #{status}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp load_bundled do
    priv_path = Application.app_dir(:mana, @bundled_path)

    case File.read(priv_path) do
      {:ok, data} ->
        case Jason.decode(data) do
          {:ok, decoded} -> decoded
          {:error, _} -> %{}
        end

      {:error, _} ->
        %{}
    end
  end

  defp save_bundled(data) do
    priv_path = Application.app_dir(:mana, @bundled_path)

    # Ensure directory exists
    priv_dir = Path.dirname(priv_path)
    File.mkdir_p!(priv_dir)

    File.write!(priv_path, Jason.encode!(data, pretty: true))
  rescue
    e ->
      Logger.error("Failed to save bundled models.dev data: #{inspect(e)}")
      :error
  end

  defp search_in_data(data, query) do
    query_lower = String.downcase(query)

    Enum.flat_map(data, fn {_provider, provider_data} ->
      models = Map.get(provider_data, "models", [])

      Enum.filter(models, fn model ->
        name = Map.get(model, "name", "")
        String.contains?(String.downcase(name), query_lower)
      end)
    end)
  end

  defp find_model_in_data(data, name) do
    Enum.find_value(data, fn {_provider, provider_data} ->
      models = Map.get(provider_data, "models", [])

      Enum.find(models, fn model ->
        Map.get(model, "name") == name
      end)
    end)
  end
end
