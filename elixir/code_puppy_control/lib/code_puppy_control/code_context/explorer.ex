defmodule CodePuppyControl.CodeContext.Explorer do
  @moduledoc """
  File and directory exploration with symbol extraction and caching.

  This GenServer provides methods to explore files and directories with
  symbol-level understanding, integrating with the Parser module for
  symbol extraction. It maintains a cache of explored files for
  improved performance on repeated access.

  ## Features

  - Single file exploration with optional content inclusion
  - Directory exploration with pattern matching
  - LRU-style cache with configurable size
  - Symbol search across directories
  - Language detection from file extensions

  ## Usage

  Start the explorer as part of your supervision tree:

      {CodePuppyControl.CodeContext.Explorer, enable_cache: true}

  Or use the global instance:

      CodePuppyControl.CodeContext.Explorer.explore_file("/path/to/file.py")
      CodePuppyControl.CodeContext.Explorer.explore_directory("/path/to/project")

  ## Cache Management

  The cache automatically evicts oldest entries when size limits are reached.
  You can manually invalidate entries:

      Explorer.invalidate_cache("/path/to/file.py")  # specific file
      Explorer.invalidate_cache()                       # all files
  """

  use GenServer

  require Logger

  alias CodePuppyControl.CodeContext.{Context, FileOutline, SymbolInfo}
  alias CodePuppyControl.FileOps
  alias CodePuppyControl.Parser

  @default_max_cache_size 100
  @default_max_files 50

  # Client API

  @doc """
  Starts the Explorer GenServer.

  ## Options

    * `:name` - GenServer registration name (default: `__MODULE__`)
    * `:enable_cache` - Whether to enable result caching (default: true)
    * `:max_cache_size` - Maximum number of cached files (default: 100)

  ## Examples

      iex> CodePuppyControl.CodeContext.Explorer.start_link([])
      {:ok, pid}
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Child specification for supervision trees.
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
  Explores a single file and returns its code context.

  ## Options

    * `:include_content` - Whether to include file content (default: true)
    * `:force_refresh` - Whether to bypass cache and re-parse (default: false)

  ## Examples

      iex> Explorer.explore_file("/path/to/file.py")
      {:ok, %Context{file_path: "/path/to/file.py", ...}}

      iex> Explorer.explore_file("/path/to/file.py", include_content: false)
      {:ok, %Context{file_path: "/path/to/file.py", content: nil, ...}}
  """
  @spec explore_file(GenServer.server(), String.t(), keyword()) ::
          {:ok, Context.t()} | {:error, term()}
  def explore_file(server \\ __MODULE__, file_path, opts \\ []) do
    GenServer.call(server, {:explore_file, file_path, opts})
  end

  @doc """
  Bang variant of `explore_file/3`.
  """
  @spec explore_file!(GenServer.server(), String.t(), keyword()) :: Context.t()
  def explore_file!(server \\ __MODULE__, file_path, opts \\ []) do
    case explore_file(server, file_path, opts) do
      {:ok, context} -> context
      {:error, reason} -> raise "Explorer failed for #{file_path}: #{inspect(reason)}"
    end
  end

  @doc """
  Gets the hierarchical outline of a file.

  ## Options

    * `:max_depth` - Maximum depth for nested symbols (default: nil for unlimited)

  ## Examples

      iex> Explorer.get_outline("/path/to/file.py")
      {:ok, %FileOutline{symbols: [...], ...}}
  """
  @spec get_outline(GenServer.server(), String.t(), keyword()) ::
          {:ok, FileOutline.t()} | {:error, term()}
  def get_outline(server \\ __MODULE__, file_path, opts \\ []) do
    GenServer.call(server, {:get_outline, file_path, opts})
  end

  @doc """
  Explores a directory and returns code contexts for supported files.

  ## Options

    * `:pattern` - File pattern to match (default: "*")
    * `:recursive` - Whether to search recursively (default: true)
    * `:max_files` - Maximum number of files to process (default: 50)
    * `:include_content` - Whether to include file content (default: false)

  ## Examples

      iex> Explorer.explore_directory("/path/to/project")
      {:ok, [%Context{...}, %Context{...}]}

      iex> Explorer.explore_directory("/path/to/project", pattern: "*.py", max_files: 20)
      {:ok, [%Context{...}]}
  """
  @spec explore_directory(GenServer.server(), String.t(), keyword()) ::
          {:ok, [Context.t()]} | {:error, term()}
  def explore_directory(server \\ __MODULE__, directory, opts \\ []) do
    GenServer.call(server, {:explore_directory, directory, opts})
  end

  @doc """
  Finds all definitions of a symbol name across a directory.

  ## Examples

      iex> Explorer.find_symbol_definitions("/path/to/project", "my_function")
      {:ok, [{"/path/to/file1.py", %SymbolInfo{name: "my_function", ...}}, ...]}
  """
  @spec find_symbol_definitions(GenServer.server(), String.t(), String.t(), keyword()) ::
          {:ok, [{String.t(), SymbolInfo.t()}]} | {:error, term()}
  def find_symbol_definitions(server \\ __MODULE__, directory, symbol_name, opts \\ []) do
    GenServer.call(server, {:find_symbol_definitions, directory, symbol_name, opts})
  end

  @doc """
  Invalidates the cache for a specific file or all files.

  ## Examples

      iex> Explorer.invalidate_cache("/path/to/file.py")
      :ok

      iex> Explorer.invalidate_cache()
      :ok
  """
  @spec invalidate_cache(GenServer.server(), String.t() | nil) :: :ok
  def invalidate_cache(server \\ __MODULE__, file_path \\ nil) do
    GenServer.call(server, {:invalidate_cache, file_path})
  end

  @doc """
  Returns cache statistics.

  ## Examples

      iex> Explorer.get_cache_stats()
      {:ok, %{cache_size: 10, parse_count: 25, cache_hits: 15, cache_misses: 10, hit_ratio: 0.6}}
  """
  @spec get_cache_stats(GenServer.server()) :: {:ok, map()}
  def get_cache_stats(server \\ __MODULE__) do
    GenServer.call(server, :get_cache_stats)
  end

  # Server Callbacks

  @impl true
  def init(opts) do
    state = %{
      enable_cache: Keyword.get(opts, :enable_cache, true),
      max_cache_size: Keyword.get(opts, :max_cache_size, @default_max_cache_size),
      cache: %{},
      cache_order: [],
      parse_count: 0,
      cache_hits: 0,
      cache_misses: 0
    }

    {:ok, state}
  end

  @impl true
  def handle_call({:explore_file, file_path, opts}, _from, state) do
    abs_path = Path.expand(file_path)
    include_content = Keyword.get(opts, :include_content, true)
    force_refresh = Keyword.get(opts, :force_refresh, false)

    # Check cache first
    cache_key = {abs_path, include_content}

    cached_result =
      if state.enable_cache and not force_refresh do
        Map.get(state.cache, cache_key)
      end

    if cached_result do
      # Update cache order (move to front for LRU)
      new_order = [cache_key | Enum.reject(state.cache_order, &(&1 == cache_key))]

      new_state = %{
        state
        | cache_order: new_order,
          cache_hits: state.cache_hits + 1
      }

      {:reply, {:ok, cached_result}, new_state}
    else
      # Parse the file
      context = do_explore_file(abs_path, include_content)

      new_state =
        if state.enable_cache do
          cache_result(state, cache_key, context)
        else
          %{state | cache_misses: state.cache_misses + 1, parse_count: state.parse_count + 1}
        end

      {:reply, {:ok, context}, new_state}
    end
  end

  @impl true
  def handle_call({:get_outline, file_path, opts}, _from, state) do
    abs_path = Path.expand(file_path)
    max_depth = Keyword.get(opts, :max_depth)

    # Check cache for existing context
    cache_key = {abs_path, false}

    context =
      if state.enable_cache and Map.has_key?(state.cache, cache_key) do
        Map.get(state.cache, cache_key)
      else
        do_explore_file(abs_path, false)
      end

    outline =
      if context.outline do
        if max_depth do
          FileOutline.limit_depth(context.outline, max_depth)
        else
          context.outline
        end
      else
        FileOutline.new("unknown", success: false, errors: ["Failed to extract outline"])
      end

    {:reply, {:ok, outline}, state}
  end

  @impl true
  def handle_call({:explore_directory, directory, opts}, _from, state) do
    dir_path = Path.expand(directory)
    pattern = Keyword.get(opts, :pattern, "*")
    recursive = Keyword.get(opts, :recursive, true)
    max_files = Keyword.get(opts, :max_files, @default_max_files)
    include_content = Keyword.get(opts, :include_content, false)

    contexts = do_explore_directory(dir_path, pattern, recursive, max_files, include_content)
    {:reply, {:ok, contexts}, state}
  end

  @impl true
  def handle_call({:find_symbol_definitions, directory, symbol_name, opts}, _from, state) do
    max_files = Keyword.get(opts, :max_files, 100)

    # Use do_explore_directory directly to avoid GenServer.call on self
    contexts = do_explore_directory(directory, "*", true, max_files, false)

    results =
      Enum.flat_map(contexts, fn context ->
        if context.outline do
          context.outline.symbols
          |> Enum.flat_map(&collect_matching_symbols(&1, symbol_name, context.file_path))
        else
          []
        end
      end)

    {:reply, {:ok, results}, state}
  end

  @impl true
  def handle_call({:invalidate_cache, nil}, _from, state) do
    Logger.debug("Cache cleared for all files")

    {:reply, :ok,
     %{state | cache: %{}, cache_order: [], parse_count: 0, cache_hits: 0, cache_misses: 0}}
  end

  @impl true
  def handle_call({:invalidate_cache, file_path}, _from, state) do
    abs_path = Path.expand(file_path)

    # Remove all cache entries for this file (both with and without content)
    keys_to_remove = [{abs_path, true}, {abs_path, false}]

    new_cache = Map.drop(state.cache, keys_to_remove)
    new_order = Enum.reject(state.cache_order, fn {path, _} -> path == abs_path end)

    Logger.debug("Cache invalidated for #{abs_path}")

    {:reply, :ok, %{state | cache: new_cache, cache_order: new_order}}
  end

  @impl true
  def handle_call(:get_cache_stats, _from, state) do
    total_requests = state.cache_hits + state.cache_misses

    stats = %{
      cache_size: map_size(state.cache),
      parse_count: state.parse_count,
      cache_hits: state.cache_hits,
      cache_misses: state.cache_misses,
      hit_ratio: if(total_requests > 0, do: state.cache_hits / total_requests, else: 0.0)
    }

    {:reply, {:ok, stats}, state}
  end

  # Private Functions

  defp do_explore_file(file_path, include_content) do
    start_time = System.monotonic_time(:millisecond)

    # Detect language
    language = detect_language(file_path)

    # Read file
    read_opts = if include_content, do: [], else: [start_line: 1, num_lines: 0]

    context =
      case FileOps.Reader.read_file(file_path, read_opts) do
        {:ok, %{content: content, num_lines: num_lines, size: size, error: nil}} ->
          # Parse symbols
          outline =
            if language && include_content do
              extract_outline(content, language, start_time)
            else
              nil
            end

          # If not including content, try extracting from file directly
          outline =
            if language && not include_content && is_nil(outline) do
              case Parser.extract_symbols_from_file(file_path, language) do
                {:ok, result} -> FileOutline.from_map(result)
                {:error, _} -> nil
              end
            else
              outline
            end

          %Context{
            file_path: file_path,
            content: if(include_content, do: content, else: nil),
            language: language,
            outline: outline,
            file_size: size,
            num_lines: num_lines,
            num_tokens: estimate_tokens(content || "", num_lines),
            parse_time_ms: System.monotonic_time(:millisecond) - start_time,
            has_errors: false,
            error_message: nil
          }

        {:ok, %{error: error}} ->
          %Context{
            file_path: file_path,
            language: language,
            has_errors: true,
            error_message: to_string(error),
            parse_time_ms: System.monotonic_time(:millisecond) - start_time
          }

        {:error, reason} ->
          %Context{
            file_path: file_path,
            language: language,
            has_errors: true,
            error_message: "Failed to read file: #{inspect(reason)}",
            parse_time_ms: System.monotonic_time(:millisecond) - start_time
          }
      end

    context
  end

  defp do_explore_directory(dir_path, pattern, recursive, max_files, include_content) do
    if not File.dir?(dir_path) do
      Logger.error("Not a directory: #{dir_path}")
      []
    else
      # Find all matching files
      files =
        if recursive do
          Path.wildcard(Path.join(dir_path, "**/" <> pattern))
        else
          Path.wildcard(Path.join(dir_path, pattern))
        end

      # Filter to supported files
      supported_files =
        Enum.filter(files, fn f ->
          File.regular?(f) and detect_language(f) != nil
        end)

      files_to_process = Enum.take(supported_files, max_files)

      Logger.info(
        "Exploring #{length(files_to_process)} files in #{dir_path} " <>
          "(#{length(supported_files)} total supported files found)"
      )

      # Process files concurrently
      files_to_process
      |> Task.async_stream(
        fn file_path ->
          try do
            do_explore_file(file_path, include_content)
          rescue
            e ->
              Logger.warning("Failed to explore #{file_path}: #{Exception.message(e)}")

              %Context{
                file_path: file_path,
                has_errors: true,
                error_message: Exception.message(e)
              }
          end
        end,
        max_concurrency: System.schedulers_online(),
        timeout: 30_000,
        on_timeout: :kill_task
      )
      |> Enum.map(fn
        {:ok, context} -> context
        {:exit, _reason} -> nil
      end)
      |> Enum.reject(&is_nil/1)
    end
  end

  defp extract_outline(content, language, _start_time) do
    case Parser.extract_symbols(content, language) do
      {:ok, result} ->
        FileOutline.from_map(result)

      {:error, reason} ->
        FileOutline.new(
          language,
          success: false,
          errors: ["Failed to extract symbols: #{inspect(reason)}"]
        )
    end
  end

  defp collect_matching_symbols(symbol, target_name, file_path) do
    results =
      if symbol.name == target_name do
        [{file_path, symbol}]
      else
        []
      end

    child_results =
      Enum.flat_map(symbol.children, &collect_matching_symbols(&1, target_name, file_path))

    results ++ child_results
  end

  defp detect_language(file_path) do
    case Path.extname(file_path) |> String.downcase() do
      ".py" -> "python"
      ".rs" -> "rust"
      ".js" -> "javascript"
      ".jsx" -> "javascript"
      ".ts" -> "typescript"
      ".tsx" -> "tsx"
      ".ex" -> "elixir"
      ".exs" -> "elixir"
      ".heex" -> "elixir"
      _ -> nil
    end
  end

  defp estimate_tokens(content, num_lines) do
    # Rough estimate: ~4 characters per token on average
    # This is a simple heuristic; for more accurate counts, use a tokenizer
    String.length(content) |> div(4)
  rescue
    _ -> num_lines * 10
  end

  defp cache_result(state, cache_key, context) do
    # Check if we need to evict
    cache_size = map_size(state.cache)

    {new_cache, new_order} =
      if cache_size >= state.max_cache_size do
        # Evict oldest entry
        {oldest_key, remaining_order} = List.pop_at(state.cache_order, -1)
        {Map.delete(state.cache, oldest_key), remaining_order}
      else
        {state.cache, state.cache_order}
      end

    # Add new entry to front (most recently used)
    updated_cache = Map.put(new_cache, cache_key, context)
    updated_order = [cache_key | new_order]

    %{
      state
      | cache: updated_cache,
        cache_order: updated_order,
        parse_count: state.parse_count + 1,
        cache_misses: state.cache_misses + 1
    }
  end
end
