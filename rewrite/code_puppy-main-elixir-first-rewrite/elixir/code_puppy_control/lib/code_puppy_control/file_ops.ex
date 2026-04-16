defmodule CodePuppyControl.FileOps do
  @moduledoc """
  Native Elixir file operations - port of turbo_ops.

  Provides list_files, grep, read_file, read_files with:
  - Concurrent processing via Task.async_stream
  - Memory-efficient streaming for large directories
  - Proper error handling
  - Security validation (no sensitive paths)

  Ported from Python code_puppy/tools/file_operations.py
  """

  require Logger

  alias CodePuppyControl.Indexer.Constants

  @type file_info :: %{
          path: String.t(),
          size: non_neg_integer(),
          type: :file | :directory,
          modified: DateTime.t()
        }

  @type grep_match :: %{
          file: String.t(),
          line_number: non_neg_integer(),
          line_content: String.t(),
          match_start: non_neg_integer(),
          match_end: non_neg_integer()
        }

  @type read_result :: %{
          path: String.t(),
          content: String.t() | nil,
          num_lines: non_neg_integer(),
          size: non_neg_integer(),
          truncated: boolean(),
          error: String.t() | nil
        }

  # Maximum entries to prevent memory exhaustion
  @max_list_files_entries 10_000

  # Maximum grep matches per search
  @max_grep_matches 1_000

  # Maximum file size for grep (in bytes)
  @max_grep_file_size 10 * 1024 * 1024

  # Maximum read file size (10MB)
  @max_read_file_size 10 * 1024 * 1024

  # ============================================================================
  # SENSITIVE PATH DEFINITIONS (Ported from Python sensitive_paths.py)
  # ============================================================================

  @sensitive_dir_prefixes MapSet.new([
                            Path.join(System.user_home!(), ".ssh"),
                            Path.join(System.user_home!(), ".aws"),
                            Path.join(System.user_home!(), ".gnupg"),
                            Path.join(System.user_home!(), ".gcp"),
                            Path.join(System.user_home!(), ".config/gcloud"),
                            Path.join(System.user_home!(), ".azure"),
                            Path.join(System.user_home!(), ".kube"),
                            Path.join(System.user_home!(), ".docker"),
                            "/etc",
                            "/private/etc",
                            "/dev",
                            "/root",
                            "/proc",
                            "/var/log"
                          ])

  @sensitive_exact_files MapSet.new([
                           Path.join(System.user_home!(), ".netrc"),
                           Path.join(System.user_home!(), ".pgpass"),
                           Path.join(System.user_home!(), ".my.cnf"),
                           Path.join(System.user_home!(), ".env"),
                           Path.join(System.user_home!(), ".bash_history"),
                           Path.join(System.user_home!(), ".npmrc"),
                           Path.join(System.user_home!(), ".pypirc"),
                           Path.join(System.user_home!(), ".gitconfig"),
                           "/etc/shadow",
                           "/etc/sudoers",
                           "/etc/passwd",
                           "/etc/master.passwd",
                           "/private/etc/shadow",
                           "/private/etc/sudoers",
                           "/private/etc/passwd",
                           "/private/etc/master.passwd"
                         ])

  @sensitive_filenames MapSet.new([".env"])

  @allowed_env_patterns MapSet.new([".env.example", ".env.sample", ".env.template"])

  @sensitive_extensions MapSet.new([
                          ".pem",
                          ".key",
                          ".p12",
                          ".pfx",
                          ".keystore"
                        ])

  @doc """
  Check if a path points to a sensitive file/directory.

  Used to block access to credentials, SSH keys, and other secrets.

  ## Examples

      iex> FileOps.sensitive_path?("/home/user/.ssh/id_rsa")
      true

      iex> FileOps.sensitive_path?("/home/user/project/main.py")
      false
  """
  @spec sensitive_path?(String.t()) :: boolean()
  def sensitive_path?(file_path) when is_binary(file_path) do
    if file_path == "" do
      false
    else
      expanded = Path.expand(file_path)

      # Check directory prefixes
      sensitive_dir_prefix =
        Enum.any?(@sensitive_dir_prefixes, fn prefix ->
          String.starts_with?(expanded, prefix <> "/") or expanded == prefix
        end)

      # Check exact-match files
      sensitive_exact = MapSet.member?(@sensitive_exact_files, expanded)

      # Check sensitive filenames
      basename = Path.basename(expanded)
      basename_lower = String.downcase(basename)

      sensitive_filename =
        cond do
          # Exact match for .env file (not .env.example, etc.)
          basename == ".env" ->
            true

          # .env.* files are sensitive except allowed patterns
          String.starts_with?(basename_lower, ".env.") ->
            not MapSet.member?(@allowed_env_patterns, basename_lower)

          # Other filenames in the sensitive list
          MapSet.member?(@sensitive_filenames, basename) ->
            true

          true ->
            false
        end

      # Check for private key files by extension
      ext = Path.extname(expanded) |> String.downcase()
      sensitive_ext = MapSet.member?(@sensitive_extensions, ext)

      sensitive_dir_prefix or sensitive_exact or sensitive_filename or sensitive_ext
    end
  end

  def sensitive_path?(_), do: false

  @doc """
  Validate a file path before performing an operation.

  Returns {:ok, normalized_path} or {:error, reason}.
  """
  @spec validate_path(String.t(), atom()) :: {:ok, String.t()} | {:error, String.t()}
  def validate_path(file_path, operation) when is_binary(file_path) do
    cond do
      file_path == "" ->
        {:error, "File path cannot be empty"}

      String.contains?(file_path, "\0") ->
        {:error, "File path contains null byte"}

      sensitive_path?(file_path) ->
        {:error,
         "Access to sensitive path blocked (#{operation}): SSH keys, cloud credentials, and system secrets are never accessible."}

      true ->
        {:ok, Path.expand(file_path)}
    end
  end

  def validate_path(_, _), do: {:error, "Invalid file path"}

  # ============================================================================
  # LIST FILES
  # ============================================================================

  @doc """
  List files in a directory with optional filtering.

  Options:
  - :recursive - boolean, default true
  - :include_hidden - boolean, default false
  - :ignore_patterns - list of glob patterns to skip
  - :max_files - integer limit

  ## Examples

      iex> FileOps.list_files("/path/to/project")
      {:ok, [%{path: "lib/file.ex", size: 1234, type: :file, modified: ~U[...]}, ...]}

      iex> FileOps.list_files("/path/to/project", recursive: false)
      {:ok, [%{path: "lib", size: 0, type: :directory, modified: ~U[...]}, ...]}
  """
  @spec list_files(String.t(), keyword()) :: {:ok, [file_info()]} | {:error, term()}
  def list_files(directory, opts \\ []) do
    recursive = Keyword.get(opts, :recursive, true)
    include_hidden = Keyword.get(opts, :include_hidden, false)
    custom_ignore_patterns = Keyword.get(opts, :ignore_patterns, [])
    max_files = Keyword.get(opts, :max_files, @max_list_files_entries)

    with {:ok, dir_path} <- validate_path(directory, "list"),
         :ok <- check_directory_exists(dir_path) do
      results =
        if recursive do
          list_files_recursive(dir_path, include_hidden, custom_ignore_patterns, max_files)
        else
          list_files_shallow(dir_path, include_hidden, max_files)
        end

      {:ok, results}
    end
  end

  defp check_directory_exists(dir_path) do
    cond do
      not File.dir?(dir_path) ->
        {:error, "Not a directory: #{dir_path}"}

      not File.exists?(dir_path) ->
        {:error, "Directory does not exist: #{dir_path}"}

      true ->
        :ok
    end
  end

  defp list_files_shallow(dir_path, include_hidden, max_files) do
    case File.ls(dir_path) do
      {:ok, entries} ->
        entries
        |> Stream.reject(fn entry ->
          not include_hidden and String.starts_with?(entry, ".")
        end)
        |> Stream.take(max_files)
        |> Stream.map(fn entry ->
          full_path = Path.join(dir_path, entry)
          build_file_info(full_path, entry, 0)
        end)
        |> Stream.reject(&is_nil/1)
        |> Enum.to_list()

      {:error, reason} ->
        Logger.warning("Failed to list directory #{dir_path}: #{inspect(reason)}")
        []
    end
  end

  defp list_files_recursive(dir_path, include_hidden, custom_ignore_patterns, max_files) do
    ignored = MapSet.union(Constants.ignored_dirs(), MapSet.new(custom_ignore_patterns))

    dir_path
    |> walk_directory(ignored, include_hidden, 0)
    |> Stream.take(max_files)
    |> Enum.to_list()
  end

  defp walk_directory(path, ignored, include_hidden, depth) do
    Stream.resource(
      fn -> [{{path, depth}, :dir}] end,
      fn
        [] ->
          {:halt, []}

        [{{current, d}, :dir} | rest] ->
          if should_ignore?(current, ignored, include_hidden) do
            {[], rest}
          else
            case File.ls(current) do
              {:ok, entries} ->
                children =
                  entries
                  |> Stream.reject(fn e ->
                    not include_hidden and hidden?(e)
                  end)
                  |> Stream.map(&Path.join(current, &1))
                  |> Stream.map(fn p ->
                    case File.lstat(p) do
                      {:ok, %File.Stat{type: :directory}} ->
                        {{p, d + 1}, :dir}

                      {:ok, %File.Stat{type: :regular}} ->
                        {{p, d + 1}, :file}

                      _ ->
                        nil
                    end
                  end)
                  |> Stream.reject(&is_nil/1)
                  |> Enum.to_list()
                  |> Enum.sort_by(fn {{p, _}, _} -> Path.basename(p) end)

                # Emit directory info for the current directory
                rel_path = Path.relative_to(current, path)

                dir_info =
                  if rel_path != "." do
                    [build_file_info(current, rel_path, d)]
                  else
                    []
                  end

                {dir_info, children ++ rest}

              {:error, _} ->
                {[], rest}
            end
          end

        [{{current, d}, :file} | rest] ->
          rel_path = Path.relative_to(current, path)
          file_info = build_file_info(current, rel_path, d)
          {[file_info], rest}
      end,
      fn _ -> :ok end
    )
    |> Stream.reject(&is_nil/1)
  end

  defp should_ignore?(path, ignored, _include_hidden) do
    basename = Path.basename(path)
    MapSet.member?(ignored, basename)
  end

  defp hidden?("." <> _), do: true
  defp hidden?(_), do: false

  defp build_file_info(full_path, relative_path, _depth) do
    case File.lstat(full_path, time: :posix) do
      {:ok, stat} ->
        type = if stat.type == :directory, do: :directory, else: :file

        modified =
          case DateTime.from_unix(stat.mtime) do
            {:ok, dt} -> dt
            _ -> DateTime.utc_now()
          end

        size = if type == :file, do: stat.size, else: 0

        # Validate the resulting path is not sensitive
        if not sensitive_path?(full_path) do
          %{
            path: relative_path,
            size: size,
            type: type,
            modified: modified
          }
        else
          nil
        end

      {:error, _} ->
        nil
    end
  end

  # ============================================================================
  # GREP
  # ============================================================================

  @doc """
  Search for pattern in files using regex.

  Options:
  - :case_sensitive - boolean, default true
  - :max_matches - integer limit
  - :file_pattern - glob pattern to filter files
  - :context_lines - number of lines around match

  ## Examples

      iex> FileOps.grep("defmodule", "/path/to/project")
      {:ok, [%{file: "lib/file.ex", line_number: 1, line_content: "defmodule MyApp do", match_start: 0, match_end: 9}, ...]}

      iex> FileOps.grep("TODO", "/path/to/project", case_sensitive: false)
      {:ok, [%{file: "lib/file.ex", line_number: 42, ...}, ...]}
  """
  @spec grep(String.t(), String.t(), keyword()) :: {:ok, [grep_match()]} | {:error, term()}
  def grep(pattern, directory, opts \\ []) do
    case_sensitive = Keyword.get(opts, :case_sensitive, true)
    max_matches = Keyword.get(opts, :max_matches, @max_grep_matches)
    file_pattern = Keyword.get(opts, :file_pattern, "*")
    context_lines = Keyword.get(opts, :context_lines, 0)

    with {:ok, dir_path} <- validate_path(directory, "grep"),
         :ok <- check_directory_exists(dir_path),
         {:ok, regex} <- build_regex(pattern, case_sensitive) do
      matches =
        dir_path
        |> stream_files_for_grep(file_pattern)
        |> Stream.flat_map(fn file_path ->
          search_file(file_path, regex, context_lines, dir_path)
        end)
        |> Stream.take(max_matches)
        |> Enum.to_list()

      {:ok, matches}
    end
  end

  defp build_regex(pattern, case_sensitive) do
    try do
      opts = if case_sensitive, do: [], else: [:caseless]
      {:ok, Regex.compile!(pattern, opts)}
    rescue
      Regex.CompileError ->
        {:error, "Invalid regex pattern: #{pattern}"}
    end
  end

  defp stream_files_for_grep(dir_path, file_pattern) do
    ignored = Constants.ignored_dirs()

    dir_path
    |> walk_directory(ignored, false, 0)
    |> Stream.filter(fn %{type: type} -> type == :file end)
    |> Stream.map(fn %{path: path} -> Path.join(dir_path, path) end)
    |> Stream.filter(fn path -> matches_pattern?(path, file_pattern) end)
  end

  defp matches_pattern?(_path, "*"), do: true

  defp matches_pattern?(path, pattern) do
    # Simple glob matching - could use Path.wildcard but that's for listing
    # This is a simplified version
    ext = Path.extname(path)
    String.contains?(path, pattern) or ext == pattern
  end

  defp search_file(file_path, regex, context_lines, base_dir) do
    # Check file size first
    case File.stat(file_path) do
      {:ok, %{size: size}} when size > @max_grep_file_size ->
        []

      {:ok, _} ->
        do_search_file(file_path, regex, context_lines, base_dir)

      {:error, _} ->
        []
    end
  end

  defp do_search_file(file_path, regex, _context_lines, base_dir) do
    case File.read(file_path) do
      {:ok, content} ->
        lines = String.split(content, "\n")
        rel_path = Path.relative_to(file_path, base_dir)

        lines
        |> Enum.with_index(1)
        |> Enum.flat_map(fn {line, line_num} ->
          case Regex.run(regex, line, return: :index) do
            nil ->
              []

            [{start, len} | _] ->
              # Strip line for display
              stripped = String.trim(line)

              truncated =
                if String.length(stripped) > 512,
                  do: String.slice(stripped, 0, 512),
                  else: stripped

              [
                %{
                  file: rel_path,
                  line_number: line_num,
                  line_content: truncated,
                  match_start: start,
                  match_end: start + len
                }
              ]
          end
        end)
        |> Enum.reject(fn match -> sensitive_path?(match.file) end)

      {:error, _} ->
        []
    end
  end

  # ============================================================================
  # READ FILE
  # ============================================================================

  @doc """
  Read a single file's contents.

  Options:
  - :start_line - integer, 1-based
  - :num_lines - integer limit
  - :encoding - atom, default :utf8

  ## Examples

      iex> FileOps.read_file("/path/to/file.ex")
      {:ok, %{path: "file.ex", content: "...", num_lines: 100, size: 1234, truncated: false}}

      iex> FileOps.read_file("/path/to/file.ex", start_line: 1, num_lines: 10)
      {:ok, %{path: "file.ex", content: "...", num_lines: 10, size: 500, truncated: true}}
  """
  @spec read_file(String.t(), keyword()) :: {:ok, read_result()} | {:error, term()}
  def read_file(path, opts \\ []) do
    start_line = Keyword.get(opts, :start_line)
    num_lines = Keyword.get(opts, :num_lines)

    with {:ok, file_path} <- validate_path(path, "read"),
         {:ok, result} <- do_read_file(file_path, start_line, num_lines) do
      {:ok, result}
    end
  end

  defp do_read_file(file_path, start_line, num_lines) do
    cond do
      not File.exists?(file_path) ->
        {:error, "File not found: #{file_path}"}

      not File.regular?(file_path) ->
        {:error, "Not a file: #{file_path}"}

      true ->
        case File.stat(file_path) do
          {:ok, %{size: size}} when size > @max_read_file_size ->
            {:error,
             "File too large (> #{@max_read_file_size} bytes). Read in chunks using start_line/num_lines options."}

          {:ok, stat} ->
            content_result =
              case File.read(file_path) do
                {:ok, content} ->
                  process_content(content, start_line, num_lines)

                {:error, reason} ->
                  {:error, "Failed to read file: #{inspect(reason)}"}
              end

            case content_result do
              {:ok, {content, truncated}} ->
                {:ok,
                 %{
                   path: file_path,
                   content: content,
                   num_lines: count_lines(content),
                   size: stat.size,
                   truncated: truncated,
                   error: nil
                 }}

              {:error, reason} ->
                {:error, reason}
            end

          {:error, reason} ->
            {:error, "Failed to stat file: #{inspect(reason)}"}
        end
    end
  end

  defp process_content(content, nil, nil) do
    {:ok, {content, false}}
  end

  defp process_content(content, start_line, num_lines) do
    lines = String.split(content, "\n")
    total_lines = length(lines)

    effective_start = max(start_line || 1, 1)
    effective_num = num_lines || total_lines

    if effective_start > total_lines do
      {:ok, {"", true}}
    else
      end_line = min(effective_start + effective_num - 1, total_lines)
      selected = Enum.slice(lines, effective_start - 1, end_line - effective_start + 1)
      result = Enum.join(selected, "\n")
      truncated = end_line < total_lines or effective_start > 1

      {:ok, {result, truncated}}
    end
  end

  defp count_lines(""), do: 0
  defp count_lines(content), do: String.split(content, "\n") |> length()

  # ============================================================================
  # READ FILES (BATCH)
  # ============================================================================

  @doc """
  Batch read multiple files concurrently.

  Options:
  - :max_concurrency - integer, default System.schedulers_online()
  - :timeout - milliseconds per file

  ## Examples

      iex> FileOps.read_files(["file1.ex", "file2.ex"])
      {:ok, [%{path: "file1.ex", content: "...", ...}, %{path: "file2.ex", content: "...", ...}]}
  """
  @spec read_files([String.t()], keyword()) :: {:ok, [read_result()]} | {:error, term()}
  def read_files(paths, opts \\ []) do
    max_concurrency = Keyword.get(opts, :max_concurrency, System.schedulers_online())
    timeout = Keyword.get(opts, :timeout, 30_000)
    read_opts = Keyword.take(opts, [:start_line, :num_lines])

    # Validate all paths first - split into valid and invalid
    {valid_paths, invalid_results} =
      Enum.reduce(paths, {[], []}, fn path, {valid, invalid} ->
        case validate_path(path, "read") do
          {:ok, normalized} ->
            {[normalized | valid], invalid}

          {:error, reason} ->
            {valid,
             [
               %{path: path, content: nil, num_lines: 0, size: 0, truncated: false, error: reason}
               | invalid
             ]}
        end
      end)

    # If no valid paths, return error
    if valid_paths == [] and invalid_results != [] do
      # Return the error results along with the error status
      {:ok, Enum.reverse(invalid_results)}
    else
      results =
        valid_paths
        |> Task.async_stream(
          fn path ->
            case read_file(path, read_opts) do
              {:ok, result} ->
                result

              {:error, reason} ->
                %{
                  path: path,
                  content: nil,
                  num_lines: 0,
                  size: 0,
                  truncated: false,
                  error: reason
                }
            end
          end,
          max_concurrency: max_concurrency,
          timeout: timeout,
          on_timeout: :kill_task
        )
        |> Enum.to_list()
        |> Enum.map(fn
          {:ok, result} ->
            result

          {:exit, reason} ->
            %{
              path: "",
              content: nil,
              num_lines: 0,
              size: 0,
              truncated: false,
              error: "Task failed: #{inspect(reason)}"
            }
        end)

      # Combine valid and invalid results
      {:ok, Enum.reverse(invalid_results) ++ results}
    end
  end
end
