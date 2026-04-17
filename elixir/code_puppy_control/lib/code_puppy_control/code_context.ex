defmodule CodePuppyControl.CodeContext do
  @moduledoc """
  Symbol-augmented code exploration for Code Puppy.

  This module provides comprehensive code exploration capabilities:

  - `SymbolInfo` - Information about individual code symbols
  - `FileOutline` - Hierarchical structure of source files
  - `Context` - Complete code context with metadata
  - `Explorer` - File/directory exploration with caching

  ## Quick Start

      # Explore a single file
      {:ok, context} = CodeContext.get_context("/path/to/file.py")
      IO.puts(context.language)  # "python"
      IO.puts(CodeContext.Context.summary(context))

      # Get file outline
      {:ok, outline} = CodeContext.get_outline("/path/to/file.py")
      functions = FileOutline.functions(outline)

      # Explore a directory
      {:ok, contexts} = CodeContext.explore_directory("/path/to/project")

  ## Architecture

  The CodeContext system is built on several layers:

  1. **Data Layer** (`SymbolInfo`, `FileOutline`, `Context`)
     - Immutable structs for representing code structure
     - Conversion to/from maps for serialization
     - Helper functions for querying and filtering

  2. **Exploration Layer** (`Explorer` GenServer)
     - File and directory traversal
     - Symbol extraction via Parser module
     - LRU cache for performance

  3. **API Layer** (this module)
     - Convenience functions for common operations
     - Global Explorer instance management

  ## Integration with Repo Compass

  CodeContext integrates with the Repo Compass indexer to provide
  symbol-augmented repository exploration. Use `explore_directory/2`
  to get an overview of code structure across your project.
  """

  alias CodePuppyControl.CodeContext.{Context, Explorer, FileOutline, SymbolInfo}

  require Logger

  @global_explorer_name :code_context_global_explorer

  # ============================================================================
  # Convenience Functions (using global Explorer instance)
  # ============================================================================

  @doc """
  Gets code context for a file.

  This is the main entry point for accessing code context information.
  It wraps the Parser results and provides a convenient interface
  for code exploration.

  ## Options

    * `:include_content` - Whether to include file content (default: true)
    * `:with_symbols` - Whether to extract symbols (default: true)

  ## Examples

      iex> {:ok, context} = CodeContext.get_context("/path/to/file.py")
      iex> context.language
      "python"
      iex> length(context.outline.symbols) > 0
      true

      iex> {:ok, context} = CodeContext.get_context("/path/to/file.py", include_content: false)
      iex> context.content
      nil
  """
  @spec get_context(String.t(), keyword()) :: {:ok, Context.t()} | {:error, term()}
  def get_context(file_path, opts \\ []) do
    with_symbols = Keyword.get(opts, :with_symbols, true)
    include_content = Keyword.get(opts, :include_content, true)

    if with_symbols do
      ensure_explorer()
      Explorer.explore_file(@global_explorer_name, file_path, include_content: include_content)
    else
      # Return context without symbol extraction
      {:ok, create_context_without_symbols(file_path, include_content)}
    end
  end

  @doc """
  Bang variant of `get_context/2`.
  """
  @spec get_context!(String.t(), keyword()) :: Context.t()
  def get_context!(file_path, opts \\ []) do
    case get_context(file_path, opts) do
      {:ok, context} -> context
      {:error, reason} -> raise "Failed to get context for #{file_path}: #{inspect(reason)}"
    end
  end

  @doc """
  Gets the hierarchical outline of a file.

  ## Options

    * `:max_depth` - Maximum depth for nested symbols (default: nil for unlimited)

  ## Examples

      iex> {:ok, outline} = CodeContext.get_outline("/path/to/file.py")
      iex> outline.language
      "python"
      iex> length(outline.symbols) >= 0
      true
  """
  @spec get_outline(String.t(), keyword()) :: {:ok, FileOutline.t()} | {:error, term()}
  def get_outline(file_path, opts \\ []) do
    ensure_explorer()
    Explorer.get_outline(@global_explorer_name, file_path, opts)
  end

  @doc """
  Bang variant of `get_outline/2`.
  """
  @spec get_outline!(String.t(), keyword()) :: FileOutline.t()
  def get_outline!(file_path, opts \\ []) do
    case get_outline(file_path, opts) do
      {:ok, outline} -> outline
      {:error, reason} -> raise "Failed to get outline for #{file_path}: #{inspect(reason)}"
    end
  end

  @doc """
  Explores a directory and returns code contexts for supported files.

  ## Options

    * `:pattern` - File pattern to match (default: "*")
    * `:recursive` - Whether to search recursively (default: true)
    * `:max_files` - Maximum number of files to process (default: 50)
    * `:include_content` - Whether to include file content (default: false)

  ## Examples

      iex> {:ok, contexts} = CodeContext.explore_directory("/path/to/project")
      iex> length(contexts) >= 0
      true

      iex> {:ok, contexts} = CodeContext.explore_directory("/path/to/project", pattern: "*.ex")
      iex> Enum.all?(contexts, &(&1.language == "elixir"))
      true
  """
  @spec explore_directory(String.t(), keyword()) :: {:ok, [Context.t()]} | {:error, term()}
  def explore_directory(directory, opts \\ []) do
    ensure_explorer()
    Explorer.explore_directory(@global_explorer_name, directory, opts)
  end

  @doc """
  Bang variant of `explore_directory/2`.
  """
  @spec explore_directory!(String.t(), keyword()) :: [Context.t()]
  def explore_directory!(directory, opts \\ []) do
    case explore_directory(directory, opts) do
      {:ok, contexts} -> contexts
      {:error, reason} -> raise "Failed to explore directory #{directory}: #{inspect(reason)}"
    end
  end

  @doc """
  Finds all definitions of a symbol name across a directory.

  ## Examples

      iex> {:ok, results} = CodeContext.find_symbol_definitions("/path/to/project", "my_function")
      iex> is_list(results)
      true
  """
  @spec find_symbol_definitions(String.t(), String.t(), keyword()) ::
          {:ok, [{String.t(), SymbolInfo.t()}]} | {:error, term()}
  def find_symbol_definitions(directory, symbol_name, opts \\ []) do
    ensure_explorer()
    Explorer.find_symbol_definitions(@global_explorer_name, directory, symbol_name, opts)
  end

  @doc """
  Formats a file outline as a human-readable string.

  ## Options

    * `:show_lines` - Whether to show line numbers (default: true)

  ## Examples

      iex> outline = %FileOutline{language: "python", symbols: [%SymbolInfo{name: "foo", kind: "function", start_line: 10}]}
      iex> CodeContext.format_outline(outline)
      "📋 Outline (python):\\n⚡ foo (L10)"
  """
  @spec format_outline(FileOutline.t(), keyword()) :: String.t()
  def format_outline(%FileOutline{} = outline, opts \\ []) do
    show_lines = Keyword.get(opts, :show_lines, true)

    lines = ["📋 Outline (#{outline.language}):"]

    symbol_lines =
      Enum.map(outline.symbols, fn symbol ->
        format_symbol(symbol, 0, show_lines)
      end)

    Enum.join(lines ++ symbol_lines, "\n")
  end

  @doc """
  Enhances a file read result with symbol information.

  This helper can be used to add symbol information to existing
  file reading operations.

  ## Examples

      iex> result = %{content: "def foo(): pass", num_tokens: 10, file_path: "/path/to/file.py"}
      iex> {:ok, enhanced} = CodeContext.enhance_read_result(result, with_symbols: true)
      iex> enhanced[:outline] != nil
      true
  """
  @spec enhance_read_result(map(), keyword()) :: {:ok, map()} | {:error, term()}
  def enhance_read_result(result, opts \\ []) do
    with_symbols = Keyword.get(opts, :with_symbols, false)
    file_path = result[:file_path] || result["file_path"]

    if with_symbols and file_path do
      try do
        outline = get_outline!(file_path)

        enhanced =
          Map.merge(result, %{
            outline: FileOutline.to_map(outline),
            symbols_available: outline.success
          })

        {:ok, enhanced}
      rescue
        e ->
          Logger.warning("Failed to enhance read_file with symbols: #{Exception.message(e)}")

          enhanced =
            Map.merge(result, %{symbols_available: false, symbols_error: Exception.message(e)})

          {:ok, enhanced}
      end
    else
      {:ok, result}
    end
  end

  @doc """
  Clears the global cache.

  ## Examples

      iex> CodeContext.invalidate_cache("/path/to/file.py")
      :ok

      iex> CodeContext.invalidate_cache()
      :ok
  """
  @spec invalidate_cache(String.t() | nil) :: :ok
  def invalidate_cache(file_path \\ nil) do
    ensure_explorer()
    Explorer.invalidate_cache(@global_explorer_name, file_path)
  end

  @doc """
  Returns global cache statistics.

  ## Examples

      iex> {:ok, stats} = CodeContext.get_cache_stats()
      iex> is_map(stats)
      true
  """
  @spec get_cache_stats() :: {:ok, map()}
  def get_cache_stats do
    ensure_explorer()
    Explorer.get_cache_stats(@global_explorer_name)
  end

  # ============================================================================
  # Global Explorer Management
  # ============================================================================

  @doc """
  Starts the global CodeExplorer instance.

  This is typically called automatically when needed, but can be
  called explicitly for control over startup timing.

  ## Options

    * `:enable_cache` - Whether to enable caching (default: true)
    * `:max_cache_size` - Maximum cache entries (default: 100)

  ## Examples

      iex> CodeContext.start_global_explorer()
      {:ok, pid}
  """
  @spec start_global_explorer(keyword()) :: GenServer.on_start()
  def start_global_explorer(opts \\ []) do
    Explorer.start_link(Keyword.merge(opts, name: @global_explorer_name))
  end

  @doc """
  Stops the global CodeExplorer instance.

  ## Examples

      iex> CodeContext.stop_global_explorer()
      :ok
  """
  @spec stop_global_explorer() :: :ok
  def stop_global_explorer do
    case Process.whereis(@global_explorer_name) do
      nil -> :ok
      pid -> GenServer.stop(pid, :normal)
    end
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp ensure_explorer do
    case Process.whereis(@global_explorer_name) do
      nil ->
        {:ok, _pid} = start_global_explorer()
        :ok

      _pid ->
        :ok
    end
  end

  defp create_context_without_symbols(file_path, include_content) do
    abs_path = Path.expand(file_path)

    language =
      case Path.extname(abs_path) |> String.downcase() do
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

    if include_content do
      case File.read(abs_path) do
        {:ok, content} ->
          num_lines = content |> String.split("\n") |> length()

          %Context{
            file_path: abs_path,
            content: content,
            language: language,
            num_lines: num_lines,
            num_tokens: String.length(content) |> div(4)
          }

        {:error, reason} ->
          %Context{
            file_path: abs_path,
            language: language,
            has_errors: true,
            error_message: "Failed to read file: #{inspect(reason)}"
          }
      end
    else
      case File.stat(abs_path) do
        {:ok, stat} ->
          %Context{
            file_path: abs_path,
            language: language,
            file_size: stat.size
          }

        {:error, reason} ->
          %Context{
            file_path: abs_path,
            language: language,
            has_errors: true,
            error_message: "Failed to stat file: #{inspect(reason)}"
          }
      end
    end
  end

  defp format_symbol(%SymbolInfo{} = symbol, indent, show_lines) do
    prefix = String.duplicate("  ", indent)

    icon =
      case symbol.kind do
        "class" -> "🏛️"
        "struct" -> "🏛️"
        "interface" -> "🔷"
        "trait" -> "🔷"
        "function" -> "⚡"
        "method" -> "🔹"
        "import" -> "📦"
        "variable" -> "📌"
        "enum" -> "🔢"
        "module" -> "📂"
        _ -> "•"
      end

    line_info = if show_lines, do: " (L#{symbol.start_line})", else: ""

    result = "#{prefix}#{icon} #{symbol.name}#{line_info}"

    child_lines =
      Enum.map(symbol.children, fn child ->
        format_symbol(child, indent + 1, show_lines)
      end)

    Enum.join([result | child_lines], "\n")
  end
end
