defmodule CodePuppyControl.Gitignore do
  @moduledoc """
  Gitignore-aware path filtering, ported from Python's code_puppy/utils/gitignore.py.

  Implements native gitignore pattern matching (no external dependencies) with support for:
  - `*` - matches any characters except `/`
  - `**` - matches zero or more directories
  - `?` - matches any single character
  - `[abc]` - character class matching
  - `[!abc]` or `[^abc]` - negated character class
  - `!pattern` - negation (un-ignore)
  - `pattern/` - directory-only patterns
  - `#` - comments
  - `/pattern` - anchored to root (relative to .gitignore location)

  The `for_directory/1` function walks up from a directory collecting all
  applicable .gitignore files, then returns a matcher that can test paths.

  Uses ETS-based caching for matchers to avoid repeated directory walks.

  ## Examples

      iex> matcher = Gitignore.for_directory("/my/repo")
      iex> Gitignore.ignored?(matcher, "build/artifact.o")
      true
      iex> Gitignore.ignored?(matcher, "src/main.ex")
      false
  """

  require Logger

  @cache_table :gitignore_cache
  @cache_ttl_ms :timer.minutes(5)
  @max_cache_entries 128

  defmodule Matcher do
    @moduledoc """
    Holds compiled gitignore patterns for a directory.
    """
    defstruct [:root, :patterns, :negations]

    @type pattern :: {String.t(), keyword()}
    @type t :: %__MODULE__{
            root: String.t(),
            patterns: [pattern()],
            negations: [pattern()]
          }
  end

  # ============================================================================
  # Public API
  # ============================================================================

  @doc """
  Build a matcher for `directory` by collecting all .gitignore files.

  Walks from the given directory up to the filesystem root, reading
  every .gitignore file encountered. Patterns from ancestor directories
  are applied first (lower priority), with patterns from closer directories
  overriding them.

  Returns `nil` if no .gitignore files are found.
  """
  @spec for_directory(String.t() | Path.t()) :: Matcher.t() | nil
  def for_directory(directory) do
    directory = Path.expand(directory)

    # Check cache first
    case cache_get(directory) do
      {:ok, matcher} ->
        matcher

      :miss ->
        matcher = build_matcher(directory)
        cache_put(directory, matcher)
        matcher
    end
  end

  @doc """
  Returns true if `path` matches any gitignore pattern in the matcher.

  `path` may be absolute or relative. If absolute, it must be a
  descendant of `matcher.root`; otherwise returns false (not ignored).

  Negation patterns (starting with `!`) are applied after inclusion patterns,
  allowing files to be explicitly un-ignored.
  """
  @spec ignored?(Matcher.t() | nil, String.t() | Path.t()) :: boolean()
  def ignored?(nil, _path), do: false

  def ignored?(%Matcher{} = matcher, path) do
    # Normalize path relative to matcher root
    rel_path = get_relative_path(matcher.root, path)

    # If path is outside root, it's not ignored by this matcher
    if rel_path == nil do
      false
    else
      do_ignored?(matcher, rel_path)
    end
  end

  @doc """
  Clear the ETS cache. Useful for tests.
  """
  @spec clear_cache() :: :ok
  def clear_cache() do
    ensure_cache_table()
    :ets.delete_all_objects(@cache_table)
    :ok
  end

  @doc """
  Parse a single gitignore pattern line into a structured format.

  Returns nil for empty lines and comments.

  ## Examples

      iex> Gitignore.parse_pattern("*.log")
      {:ok, "*.log", is_negation: false, is_directory: false, anchored: false}

      iex> Gitignore.parse_pattern("!important.log")
      {:ok, "important.log", is_negation: true, is_directory: false, anchored: false}

      iex> Gitignore.parse_pattern("build/")
      {:ok, "build", is_negation: false, is_directory: true, anchored: false}

      iex> Gitignore.parse_pattern("/rooted.txt")
      {:ok, "rooted.txt", is_negation: false, is_directory: false, anchored: true}
  """
  @spec parse_pattern(String.t()) :: {:ok, String.t(), keyword()} | nil
  def parse_pattern(line) do
    line = String.trim(line)

    cond do
      # Empty line or comment
      line == "" or String.starts_with?(line, "#") ->
        nil

      # Negation pattern
      String.starts_with?(line, "!") ->
        pattern = String.slice(line, 1..-1//1) |> String.trim()
        parse_attributes(pattern, is_negation: true)

      # Regular pattern
      true ->
        parse_attributes(line, is_negation: false)
    end
  end

  @doc """
  Test if a path matches a gitignore pattern.

  Supports all standard gitignore pattern syntax.

  ## Examples

      iex> Gitignore.pattern_match?("*.log", "debug.log")
      true

      iex> Gitignore.pattern_match?("*.log", "debug.txt")
      false

      iex> Gitignore.pattern_match?("doc/*.txt", "doc/readme.txt")
      true

      iex> Gitignore.pattern_match?("doc/*.txt", "doc/api/readme.txt")
      false
  """
  @spec pattern_match?(String.t(), String.t()) :: boolean()
  def pattern_match?(pattern, path) do
    # Check if pattern ends with / (directory-only)
    {pattern, dir_only} =
      if String.ends_with?(pattern, "/") do
        {String.slice(pattern, 0..-2//1), true}
      else
        {pattern, false}
      end

    # Check if pattern is anchored (starts with /)
    anchored = String.starts_with?(pattern, "/")
    pattern = if anchored, do: String.slice(pattern, 1..-1//1), else: pattern

    matches = matches_pattern?(pattern, path, anchored)

    if dir_only do
      # Directory-only pattern only matches if path is a directory
      # We check if path ends with / or has no extension (rough heuristic)
      matches and (String.ends_with?(path, "/") or not String.contains?(path, "."))
    else
      matches
    end
  end

  # ============================================================================
  # Internal Implementation
  # ============================================================================

  # Parse pattern attributes (directory-only, anchored)
  defp parse_attributes(pattern, attrs) do
    # Check for trailing / (directory-only)
    {pattern, is_dir} =
      if String.ends_with?(pattern, "/") do
        {String.slice(pattern, 0..-2//1), true}
      else
        {pattern, false}
      end

    # Check for leading / (anchored to root)
    anchored = String.starts_with?(pattern, "/")
    pattern = if anchored, do: String.slice(pattern, 1..-1//1), else: pattern

    {:ok, pattern,
     is_negation: Keyword.get(attrs, :is_negation, false),
     is_directory: is_dir,
     anchored: anchored}
  end

  # Build matcher by walking up directory tree
  defp build_matcher(directory) do
    lines = collect_gitignore_lines(directory)

    patterns = parse_patterns(lines)

    # Return nil if no valid patterns found (only comments/blank lines)
    if patterns == [] do
      nil
    else
      # Split into inclusion and negation patterns
      {inclusions, negations} =
        Enum.split_with(patterns, fn {_, attrs} ->
          not Keyword.get(attrs, :is_negation, false)
        end)

      %Matcher{
        root: directory,
        patterns: inclusions,
        negations: negations
      }
    end
  end

  # Collect lines from all .gitignore files walking up the tree
  defp collect_gitignore_lines(directory) do
    directory
    |> walk_ancestors()
    |> Enum.reverse()
    |> Enum.flat_map(&read_gitignore/1)
  end

  # Walk up from directory to root, collecting directories
  defp walk_ancestors(directory) do
    Stream.unfold(directory, fn
      nil ->
        nil

      current ->
        parent = Path.dirname(current)
        # Stop when we reach root (parent == current)
        next = if parent != current, do: parent, else: nil
        {current, next}
    end)
  end

  # Read .gitignore file if it exists
  defp read_gitignore(dir) do
    gitignore_path = Path.join(dir, ".gitignore")

    case File.read(gitignore_path) do
      {:ok, content} ->
        String.split(content, "\n")

      {:error, _} ->
        []
    end
  end

  # Parse all pattern lines, returning {pattern, attrs} tuples
  defp parse_patterns(lines) do
    lines
    |> Enum.map(&parse_pattern/1)
    |> Enum.reject(&is_nil/1)
    |> Enum.map(fn {:ok, pattern, attrs} -> {pattern, attrs} end)
  end

  # Get relative path from root, handling absolute/relative input
  defp get_relative_path(root, path) do
    # If path is already relative, use it directly
    if Path.type(path) == :relative do
      path
    else
      path = Path.expand(path)

      case Path.relative_to(path, root) do
        ^path when path != root ->
          # Not under root
          nil

        rel_path ->
          rel_path
      end
    end
  end

  # Check if path is ignored by matcher
  defp do_ignored?(%Matcher{} = matcher, rel_path) do
    # Test against inclusion patterns
    included =
      Enum.any?(matcher.patterns, fn {pat, attrs} ->
        anchored = Keyword.get(attrs, :anchored, false)
        matches_pattern?(pat, rel_path, anchored)
      end)

    if not included do
      false
    else
      # Test against negation patterns - any match un-ignores the file
      negated =
        Enum.any?(matcher.negations, fn {pat, attrs} ->
          anchored = Keyword.get(attrs, :anchored, false)
          matches_pattern?(pat, rel_path, anchored)
        end)

      not negated
    end
  end

  # Main pattern matching logic
  defp matches_pattern?(pattern, path, anchored) do
    # Handle escaped characters first (convert to special marker)
    {pattern, path} = handle_escaped_chars(pattern, path)

    # Normalize path separators
    path = String.replace(path, "\\", "/")
    pattern = String.replace(pattern, "\\", "/")

    # Split pattern into segments for ** handling
    pat_segments = String.split(pattern, "/")
    path_segments = String.split(path, "/")

    cond do
      # Pattern contains ** (matches across directories)
      Enum.member?(pat_segments, "**") ->
        matches_double_star?(pat_segments, path_segments, anchored)

      # Anchored pattern (must match from root)
      anchored ->
        segments_match?(pat_segments, Enum.take(path_segments, length(pat_segments)))

      # Unanchored pattern (can match at any depth)
      true ->
        matches_unanchored?(pat_segments, path_segments)
    end
  end

  # Convert escaped characters to temporary markers to protect them during matching
  defp handle_escaped_chars(pattern, path) do
    # Replace escaped special chars in pattern with unique markers
    pattern =
      pattern
      |> String.replace("\\*", "<<ESCAPED_STAR>>")
      |> String.replace("\\?", "<<ESCAPED_QUESTION>>")
      |> String.replace("\\[", "<<ESCAPED_LBRACKET>>")
      |> String.replace("\\]", "<<ESCAPED_RBRACKET>>")

    # Also escape the same chars in path for exact matching
    path =
      path
      |> String.replace("*", "<<ESCAPED_STAR>>")
      |> String.replace("?", "<<ESCAPED_QUESTION>>")
      |> String.replace("[", "<<ESCAPED_LBRACKET>>")
      |> String.replace("]", "<<ESCAPED_RBRACKET>>")

    {pattern, path}
  end

  # Match ** patterns (can span directory boundaries)
  defp matches_double_star?(pat_segments, path_segments, _anchored) do
    # Split pattern around **
    {before_star, after_star} = split_at_double_star(pat_segments)

    cond do
      # ** at start: matches at any depth (including root)
      # e.g., **/deep_file matches deep_file, a/deep_file, a/b/deep_file
      before_star == [] ->
        if after_star == [] do
          # Just ** - matches anything
          true
        else
          # Try to match suffix at any position in path
          suffix_len = length(after_star)

          if suffix_len > length(path_segments) do
            false
          else
            # Match suffix at the end (or at root if that's where it is)
            max_start = max(length(path_segments) - suffix_len, 0)

            Enum.any?(0..max_start, fn start_idx ->
              suffix = Enum.slice(path_segments, start_idx, suffix_len)
              segments_match?(after_star, suffix)
            end)
          end
        end

      # ** at end: matches anything nested under prefix
      # e.g., docs/** matches docs/readme.md, docs/api/reference.md
      after_star == [] ->
        prefix_len = length(before_star)

        if prefix_len > length(path_segments) do
          false
        else
          prefix_segments = Enum.take(path_segments, prefix_len)
          segments_match?(before_star, prefix_segments)
        end

      # ** in middle: prefix must match before **, suffix must match after
      true ->
        prefix_len = length(before_star)
        suffix_len = length(after_star)

        if prefix_len + suffix_len > length(path_segments) do
          false
        else
          # Match prefix at start
          prefix_segments = Enum.take(path_segments, prefix_len)
          prefix_match = segments_match?(before_star, prefix_segments)

          # Match suffix at end (anywhere after prefix)
          min_suffix_start = prefix_len
          max_suffix_start = length(path_segments) - suffix_len

          prefix_match and
            Enum.any?(min_suffix_start..max_suffix_start, fn start_idx ->
              suffix = Enum.slice(path_segments, start_idx, suffix_len)
              segments_match?(after_star, suffix)
            end)
        end
    end
  end

  defp split_at_double_star(segments) do
    case Enum.split_while(segments, &(&1 != "**")) do
      {before, ["**" | after_rest]} -> {before, after_rest}
      {before, []} -> {before, []}
    end
  end

  # Check if pattern matches at any position in path
  # For patterns without "/", match against the basename (last segment) at any depth
  # For patterns with "/", match at the corresponding depth
  defp matches_unanchored?(pat_segments, path_segments) do
    pat_len = length(pat_segments)
    path_len = length(path_segments)

    if pat_len == 1 do
      # Pattern has no "/" (like "*.log") - matches against last segment at any depth
      # This matches Python pathspec behavior where unanchored patterns match at any depth
      last_segment = List.last(path_segments)
      segments_match?(pat_segments, [last_segment])
    else
      # Pattern has "/" (like "dir/*.txt"), can match at any depth
      if pat_len > path_len do
        false
      else
        Enum.any?(0..(path_len - pat_len), fn start_idx ->
          subsegments = Enum.slice(path_segments, start_idx, pat_len)
          segments_match?(pat_segments, subsegments)
        end)
      end
    end
  end

  # Check if two segment lists match
  defp segments_match?([], []), do: true
  defp segments_match?([], _), do: false
  defp segments_match?(_, []), do: false

  defp segments_match?([pat_seg | pat_rest], [path_seg | path_rest]) do
    segment_match?(pat_seg, path_seg) and segments_match?(pat_rest, path_rest)
  end

  # Match a single segment
  defp segment_match?(pattern, path) do
    match_chars(String.to_charlist(pattern), String.to_charlist(path))
  end

  # Character-level matching with glob support
  defp match_chars([], []), do: true
  defp match_chars([], [_ | _]), do: false

  # * matches any characters except /
  defp match_chars([?* | pat_rest], path) do
    # Try all possible lengths for *
    {before_slash, _} = Enum.split_while(path, &(&1 != ?/))
    max_len = length(before_slash)

    Enum.any?(0..max_len, fn i ->
      {consumed, remaining} = Enum.split(path, i)
      # * cannot match /
      if Enum.any?(consumed, &(&1 == ?/)) do
        false
      else
        match_chars(pat_rest, remaining)
      end
    end)
  end

  # ? matches any single character except /
  defp match_chars([?\? | pat_rest], [p | path_rest]) when p != ?/,
    do: match_chars(pat_rest, path_rest)

  defp match_chars([?\? | _], _), do: false

  # Character class [abc] or [!abc]
  defp match_chars([?[ | pat_rest], [p | path_rest]) do
    case parse_char_class(pat_rest, [], true) do
      {:ok, {:negated, chars}, rest_of_pattern} ->
        # Negated class: match if p is NOT in chars
        if Enum.member?(chars, p) do
          false
        else
          match_chars(rest_of_pattern, path_rest)
        end

      {:ok, chars, rest_of_pattern} when is_list(chars) ->
        # Regular class: match if p is in chars
        if Enum.member?(chars, p) do
          match_chars(rest_of_pattern, path_rest)
        else
          false
        end

      :error ->
        false
    end
  end

  defp match_chars([?[ | _], []), do: false

  # Escaped characters
  defp match_chars([?\\, c | pat_rest], [p | path_rest]) when c == p,
    do: match_chars(pat_rest, path_rest)

  defp match_chars([?\\, _ | _], [_ | _]), do: false

  # Regular character match
  defp match_chars([c | pat_rest], [c | path_rest]), do: match_chars(pat_rest, path_rest)

  # No match - pattern char doesn't equal path char
  defp match_chars([_ | _], [_ | _]), do: false

  # No match - ran out of path but still have pattern
  defp match_chars([_ | _], []), do: false

  # Parse character class like [abc] or [!abc] or [^abc]
  # Returns {:ok, chars, rest_of_pattern} or {:ok, {:negated, chars}, rest_of_pattern}
  # where chars is a list of allowed characters

  # Track if we're at the first character to handle ] as literal
  defp parse_char_class(chars, acc, first_char)

  defp parse_char_class([], _acc, _), do: :error

  # Negated class starts with ! or ^ (only at first position)
  defp parse_char_class([?! | rest], acc, true), do: parse_char_class_negated(rest, acc, false)
  defp parse_char_class([?^ | rest], acc, true), do: parse_char_class_negated(rest, acc, false)

  # ] as first char is literal, otherwise it's closing the class
  defp parse_char_class([?] | rest], acc, true) do
    # ] at first position is literal
    parse_char_class(rest, [?] | acc], false)
  end

  defp parse_char_class([?] | rest], acc, false), do: {:ok, Enum.reverse(acc), rest}

  # Regular character
  defp parse_char_class([c | rest], acc, _) do
    # Handle ranges like a-z
    case rest do
      [?-, end_char | rest_after] when end_char != ?] and c < end_char ->
        chars = Enum.to_list(c..end_char)
        parse_char_class(rest_after, chars ++ acc, false)

      _ ->
        parse_char_class(rest, [c | acc], false)
    end
  end

  defp parse_char_class_negated([], _acc, _), do: :error

  # ] as first char in negated class is literal
  defp parse_char_class_negated([?] | rest], acc, true) do
    parse_char_class_negated(rest, [?] | acc], false)
  end

  # Closing bracket - return negated class
  defp parse_char_class_negated([?] | rest], acc, false),
    do: {:ok, {:negated, Enum.reverse(acc)}, rest}

  defp parse_char_class_negated([c | rest], acc, _) do
    case rest do
      [?-, end_char | rest_after] when end_char != ?] and c < end_char ->
        chars = Enum.to_list(c..end_char)
        parse_char_class_negated(rest_after, chars ++ acc, false)

      _ ->
        parse_char_class_negated(rest, [c | acc], false)
    end
  end

  # ============================================================================
  # ETS Cache Implementation
  # ============================================================================

  defp ensure_cache_table() do
    case :ets.whereis(@cache_table) do
      :undefined ->
        :ets.new(@cache_table, [
          :set,
          :named_table,
          :public,
          read_concurrency: true,
          write_concurrency: true
        ])

      _ ->
        :ok
    end
  end

  defp cache_get(directory) do
    ensure_cache_table()

    case :ets.lookup(@cache_table, directory) do
      [{^directory, matcher, timestamp}] ->
        if System.monotonic_time(:millisecond) - timestamp < @cache_ttl_ms do
          {:ok, matcher}
        else
          :ets.delete(@cache_table, directory)
          :miss
        end

      [] ->
        :miss
    end
  end

  defp cache_put(directory, matcher) do
    ensure_cache_table()

    # Prune if cache is too large (simple LRU approximation)
    if :ets.info(@cache_table, :size) >= @max_cache_entries do
      # Delete oldest entries
      all_entries = :ets.tab2list(@cache_table)
      sorted = Enum.sort_by(all_entries, &elem(&1, 2), :asc)
      to_delete = Enum.take(sorted, div(@max_cache_entries, 4))

      Enum.each(to_delete, fn {key, _, _} ->
        :ets.delete(@cache_table, key)
      end)
    end

    :ets.insert(@cache_table, {directory, matcher, System.monotonic_time(:millisecond)})
  end
end
