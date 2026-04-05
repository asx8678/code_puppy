defmodule Mana.Config.Store do
  @moduledoc """
  GenServer-based configuration store with ETS caching.

  Provides fast concurrent reads via ETS and durable writes to JSON files.
  Features automatic flushing of dirty state every 5 seconds.

  ## Architecture

  - ETS table `:mana_config` for fast concurrent reads
  - GenServer state tracks dirty state and manages flush timer
  - JSON file storage for persistence

  ## Usage

      # Start the store (typically done by supervision tree)
      Mana.Config.Store.start_link([])

      # Fast reads (direct ETS lookup, no GenServer call)
      Mana.Config.Store.get(:some_key, default)

      # Writes go through GenServer for coordination
      Mana.Config.Store.put(:some_key, value)

      # Manual flush
      Mana.Config.Store.flush()
  """

  use GenServer

  require Logger

  alias Mana.Config.Paths

  @table :mana_config
  @flush_interval_ms 5_000
  @pubsub_topic "mana:config"

  # Client API

  @doc """
  Starts the Config Store GenServer.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Returns the child specification for supervision trees.
  """
  @spec child_spec(keyword()) :: Supervisor.child_spec()
  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :permanent
    }
  end

  @doc """
  Reads a value from the configuration store.

  This is a fast ETS lookup that bypasses the GenServer.
  """
  @spec get(atom(), any()) :: any()
  def get(key, default \\ nil) do
    case :ets.lookup(@table, key) do
      [{^key, value}] -> value
      [] -> default
    end
  end

  @doc """
  Writes a value to the configuration store.

  The value is written to ETS immediately and the file is flushed
  asynchronously within 5 seconds.
  """
  @spec put(atom(), any(), keyword()) :: :ok
  def put(key, value, opts \\ []) do
    GenServer.call(__MODULE__, {:put, key, value, opts})
  end

  @doc """
  Flushes the current configuration to disk.

  Writes all dirty keys to the JSON config file.
  """
  @spec flush() :: :ok | {:error, term()}
  def flush do
    GenServer.call(__MODULE__, :flush)
  end

  @doc """
  Loads configuration from disk into ETS.

  Called automatically on startup, but can be called manually
  to reload from disk.
  """
  @spec load_config() :: :ok | {:error, term()}
  def load_config do
    GenServer.call(__MODULE__, :load_config)
  end

  # Server Callbacks

  @impl true
  def init(_opts) do
    # Create ETS table with read concurrency for fast lookups
    :ets.new(@table, [
      :ordered_set,
      :named_table,
      :public,
      read_concurrency: true
    ])

    # Ensure directories exist
    Paths.ensure_dirs()

    # Load existing configuration
    config = load_from_file()

    # Populate ETS with safe atom conversion
    Enum.each(config, fn {key, value} ->
      case safe_to_atom(key) do
        {:ok, atom_key} -> :ets.insert(@table, {atom_key, value})
        :skip -> Logger.debug("Skipping unknown config key: #{key}")
      end
    end)

    {:ok, %{config: config, dirty: false, flush_timer: nil}}
  end

  @impl true
  def handle_call({:put, key, value, _opts}, _from, state) do
    # Update ETS directly (it's public)
    :ets.insert(@table, {key, value})

    # Mark as dirty and schedule flush
    new_state = schedule_flush(%{state | dirty: true})

    # Broadcast change
    broadcast_change(key, value)

    {:reply, :ok, new_state}
  end

  @impl true
  def handle_call(:flush, _from, state) do
    result = flush_to_file(state)
    new_state = cancel_flush_timer(%{state | dirty: false})
    {:reply, result, new_state}
  end

  @impl true
  def handle_call(:load_config, _from, state) do
    config = load_from_file()

    # Clear and repopulate ETS with safe atom conversion
    :ets.delete_all_objects(@table)

    Enum.each(config, fn {key, value} ->
      case safe_to_atom(key) do
        {:ok, atom_key} -> :ets.insert(@table, {atom_key, value})
        :skip -> Logger.debug("Skipping unknown config key: #{key}")
      end
    end)

    {:reply, :ok, %{state | config: config, dirty: false}}
  end

  @impl true
  def handle_info(:do_flush, state) do
    result = flush_to_file(state)
    new_state = %{state | dirty: false, flush_timer: nil}

    if result != :ok do
      # If flush failed, mark dirty again to retry
      {:noreply, schedule_flush(new_state)}
    else
      {:noreply, new_state}
    end
  end

  # Private Functions

  defp schedule_flush(%{dirty: true} = state) do
    if state.flush_timer do
      Process.cancel_timer(state.flush_timer)
    end

    timer = Process.send_after(self(), :do_flush, @flush_interval_ms)
    %{state | flush_timer: timer}
  end

  defp schedule_flush(state), do: state

  defp cancel_flush_timer(%{flush_timer: nil} = state), do: state

  defp cancel_flush_timer(%{flush_timer: timer} = state) do
    Process.cancel_timer(timer)
    %{state | flush_timer: nil}
  end

  defp load_from_file do
    file_path = Paths.config_file()

    case File.read(file_path) do
      {:ok, contents} ->
        case Jason.decode(contents) do
          {:ok, config} when is_map(config) -> config
          _ -> %{}
        end

      {:error, :enoent} ->
        %{}

      {:error, _reason} ->
        %{}
    end
  end

  defp flush_to_file(_state) do
    file_path = Paths.config_file()

    # Build current config from ETS
    current_config =
      :ets.tab2list(@table)
      |> Enum.map(fn {key, value} -> {Atom.to_string(key), value} end)
      |> Map.new()

    case Jason.encode(current_config, pretty: true) do
      {:ok, json} ->
        case File.write(file_path, json) do
          :ok -> :ok
          error -> error
        end

      error ->
        error
    end
  end

  defp broadcast_change(key, value) do
    # Stub for Phoenix.PubSub - just log for now
    # In the future, this will broadcast via Phoenix.PubSub
    Logger.debug("Config change: #{key} = #{inspect(value)} (topic: #{@pubsub_topic})")
    :ok
  end

  defp safe_to_atom(key) when is_binary(key) do
    {:ok, String.to_existing_atom(key)}
  rescue
    ArgumentError -> :skip
  end
end
