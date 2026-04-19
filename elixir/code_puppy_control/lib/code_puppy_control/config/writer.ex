defmodule CodePuppyControl.Config.Writer do
  @moduledoc """
  Atomic write-back for `puppy.cfg`.

  Writes are performed via a temporary file in the same directory as the
  target, then renamed over the original. On Unix this is a single atomic
  `mv(2)` — readers never see a half-written file.

  After each successful write, the loader cache is invalidated so the next
  read picks up fresh data.

  ## Usage

      # Set a single key
      Writer.set_value("model", "gpt-5")

      # Set multiple keys at once
      Writer.set_values(%{"model" => "gpt-5", "yolo_mode" => "true"})

      # Remove a key
      Writer.delete_value("old_key")

  ## Concurrency

  All write operations serialize through a single `GenServer` to prevent
  lost updates from concurrent writers. Reads remain lock-free via
  `:persistent_term`.
  """

  use GenServer

  require Logger

  alias CodePuppyControl.Config.{Loader, Paths}

  # ── Client API ──────────────────────────────────────────────────────────

  @doc """
  Start the writer GenServer. Called by the supervision tree.
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, __MODULE__, __MODULE__)
    GenServer.start_link(__MODULE__, [], name: name)
  end

  @doc """
  Set a single key in the default section and persist to disk.
  """
  @spec set_value(String.t(), String.t()) :: :ok
  def set_value(key, value) do
    GenServer.call(__MODULE__, {:set_value, key, value})
  end

  @doc """
  Set multiple key-value pairs in the default section atomically.
  """
  @spec set_values(%{String.t() => String.t()}) :: :ok
  def set_values(kv_map) when is_map(kv_map) do
    GenServer.call(__MODULE__, {:set_values, kv_map})
  end

  @doc """
  Remove a key from the default section.
  """
  @spec delete_value(String.t()) :: :ok
  def delete_value(key) do
    GenServer.call(__MODULE__, {:delete_value, key})
  end

  @doc """
  Write an entire config map to disk (used by migrations and bulk updates).
  """
  @spec write_config(Loader.config()) :: :ok
  def write_config(config) do
    GenServer.call(__MODULE__, {:write_config, config})
  end

  @doc """
  Synchronous write: set a value without going through the GenServer.
  Useful during shutdown when the GenServer may not be available.

  **Warning**: not safe for concurrent callers — use only when you know
  there are no other writers.
  """
  @spec unsafe_set_value(String.t(), String.t()) :: :ok
  def unsafe_set_value(key, value) do
    config = Loader.get_cached()
    section = Loader.default_section()
    section_map = Map.get(config, section, %{})
    updated = Map.put(config, section, Map.put(section_map, key, value))
    do_write(updated)
  end

  # ── GenServer Callbacks ─────────────────────────────────────────────────

  @impl true
  def init(_opts) do
    {:ok, %{}}
  end

  @impl true
  def handle_call({:set_value, key, value}, _from, state) do
    config = Loader.get_cached()
    section = Loader.default_section()
    section_map = Map.get(config, section, %{})
    updated = Map.put(config, section, Map.put(section_map, key, value))
    do_write(updated)
    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:set_values, kv_map}, _from, state) do
    config = Loader.get_cached()
    section = Loader.default_section()
    section_map = Map.get(config, section, %{})

    updated_section =
      Enum.reduce(kv_map, section_map, fn {k, v}, acc -> Map.put(acc, k, v) end)

    updated = Map.put(config, section, updated_section)
    do_write(updated)
    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:delete_value, key}, _from, state) do
    config = Loader.get_cached()
    section = Loader.default_section()
    section_map = Map.get(config, section, %{})
    updated_section = Map.delete(section_map, key)
    updated = Map.put(config, section, updated_section)
    do_write(updated)
    {:reply, :ok, state}
  end

  @impl true
  def handle_call({:write_config, config}, _from, state) do
    do_write(config)
    {:reply, :ok, state}
  end

  # ── Private ─────────────────────────────────────────────────────────────

  @spec do_write(Loader.config()) :: :ok
  defp do_write(config) do
    path = Paths.config_file()
    content = serialize(config)
    atomic_write(path, content)
    Loader.invalidate()
    :ok
  end

  @spec serialize(Loader.config()) :: String.t()
  defp serialize(config) do
    config
    |> Enum.sort_by(fn {section, _} -> section end)
    |> Enum.map_join("\n", fn {section, kv_map} ->
      section_header = "[#{section}]"

      pairs =
        kv_map
        |> Enum.sort_by(fn {k, _} -> k end)
        |> Enum.map_join("\n", fn {k, v} -> "#{k} = #{v}" end)

      "#{section_header}\n#{pairs}"
    end)
    |> then(&(&1 <> "\n"))
  end

  @spec atomic_write(String.t(), String.t()) :: :ok
  defp atomic_write(path, content) do
    dir = Path.dirname(path)
    File.mkdir_p!(dir)

    tmp_path = Path.join(dir, ".puppy.cfg.#{:erlang.unique_integer([:positive])}.tmp")

    case File.write(tmp_path, content, [:sync]) do
      :ok ->
        case File.rename(tmp_path, path) do
          :ok ->
            :ok

          {:error, reason} ->
            File.rm(tmp_path)
            Logger.error("Failed to rename #{tmp_path} -> #{path}: #{reason}")
            raise "Atomic write failed: rename error #{reason}"
        end

      {:error, reason} ->
        Logger.error("Failed to write temp file #{tmp_path}: #{reason}")
        raise "Atomic write failed: write error #{reason}"
    end
  end
end
