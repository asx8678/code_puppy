defmodule Mana.Commands.Diff do
  @moduledoc """
  Git diff integration command.

  Shows pending file changes via git diff with optional --staged/--cached flags.
  Provides colorized output and summary statistics.

  ## Commands

  - `/diff` - Show unstaged changes
  - `/diff --staged` - Show staged changes
  - `/diff --cached` - Alias for --staged
  - `/diff <path>` - Show diff for specific file/directory
  - `/diff stats` - Show summary statistics only

  ## Examples

      /diff
      # Shows unstaged changes with colorized output

      /diff --staged
      # Shows staged changes ready for commit

      /diff lib/mana/commands/
      # Shows changes in specific directory

      /diff stats
      # Shows: 5 files changed, +42/-10 lines
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Shell.Executor

  # ANSI color codes for diff highlighting
  # Green
  @color_addition "\e[32m"
  # Red
  @color_deletion "\e[31m"
  # Cyan
  @color_header "\e[36m"
  @color_reset "\e[0m"

  @impl true
  def name, do: "/diff"

  @impl true
  def description, do: "Show pending file changes (git diff integration)"

  @impl true
  def usage, do: "/diff [--staged|--cached] [path] | /diff stats"

  @impl true
  def execute(args, _context) do
    case parse_args(args) do
      {:ok, opts} -> run_diff(opts)
      {:error, reason} -> {:error, reason}
    end
  end

  # Argument parsing

  defp parse_args([]), do: {:ok, %{staged: false, path: nil, stats: false}}

  defp parse_args(["stats"]), do: {:ok, %{staged: false, path: nil, stats: true}}

  defp parse_args(["--staged" | rest]), do: parse_path_staged(rest, %{staged: true, stats: false})
  defp parse_args(["--cached" | rest]), do: parse_path_staged(rest, %{staged: true, stats: false})

  defp parse_args([path | _]) when is_binary(path) do
    expanded = Path.expand(path)

    if File.exists?(expanded) do
      {:ok, %{staged: false, path: expanded, stats: false}}
    else
      {:error, "Path does not exist: #{path}"}
    end
  end

  defp parse_path_staged(["stats"], opts), do: {:ok, Map.merge(opts, %{stats: true, path: nil})}

  defp parse_path_staged([path], opts) do
    expanded = Path.expand(path)

    if File.exists?(expanded) do
      {:ok, Map.put(opts, :path, expanded)}
    else
      {:error, "Path does not exist: #{path}"}
    end
  end

  defp parse_path_staged([], opts), do: {:ok, Map.put(opts, :path, nil)}

  defp parse_path_staged(_, _opts), do: {:error, "Usage: #{usage()}"}

  # Diff execution

  defp run_diff(%{stats: true} = opts) do
    with {:ok, git_root} <- find_git_root(),
         {:ok, stats} <- get_diff_stats(git_root, opts.staged) do
      {:ok, format_stats(stats, opts.staged)}
    else
      {:error, :not_git_repo} ->
        {:error, "Not a git repository (or any parent up to mount point)"}

      {:error, reason} ->
        {:error, "Failed to get diff stats: #{inspect(reason)}"}
    end
  end

  defp run_diff(opts) do
    with {:ok, git_root} <- find_git_root(),
         {:ok, diff_output} <- get_diff_output(git_root, opts.staged, opts.path) do
      if diff_output == "" do
        message = if opts.staged, do: "No staged changes.", else: "No unstaged changes."
        {:ok, message}
      else
        {:ok, colorize_diff(diff_output)}
      end
    else
      {:error, :not_git_repo} ->
        {:error, "Not a git repository (or any parent up to mount point)"}

      {:error, reason} ->
        {:error, "Failed to get diff: #{inspect(reason)}"}
    end
  end

  # Git operations

  defp find_git_root do
    cwd = File.cwd!()

    case Executor.execute("git rev-parse --git-dir", cwd, 5_000) do
      {:ok, %{exit_code: 0, stdout: git_dir}} ->
        git_root = git_dir |> String.trim() |> Path.dirname() |> Path.expand()
        {:ok, git_root}

      _ ->
        {:error, :not_git_repo}
    end
  end

  defp get_diff_output(git_root, staged, path) do
    args = build_diff_args(staged, path)
    command = "git #{Enum.join(args, " ")}"

    case Executor.execute(command, git_root, 30_000) do
      {:ok, %{exit_code: 0, stdout: stdout}} -> {:ok, stdout}
      # No changes is exit 1 sometimes
      {:ok, %{exit_code: 1, stdout: stdout}} -> {:ok, stdout}
      _ -> {:error, :git_failed}
    end
  end

  defp get_diff_stats(git_root, staged) do
    args = if staged, do: "git diff --staged --stat", else: "git diff --stat"

    case Executor.execute(args, git_root, 10_000) do
      {:ok, %{exit_code: 0, stdout: stdout}} -> parse_diff_stat(stdout)
      {:ok, %{exit_code: 1, stdout: stdout}} -> parse_diff_stat(stdout)
      _ -> {:error, :git_failed}
    end
  end

  defp build_diff_args(staged, nil) do
    if staged, do: ["diff", "--staged"], else: ["diff"]
  end

  defp build_diff_args(staged, path) do
    base = if staged, do: ["diff", "--staged"], else: ["diff"]
    base ++ ["--", path]
  end

  # Diff stat parsing

  defp parse_diff_stat(output) do
    lines = String.split(output, "\n", trim: true)

    {files, insertions, deletions} =
      Enum.reduce(lines, {0, 0, 0}, fn line, {f, ins, del} ->
        case parse_stat_line(line) do
          {:file, additions, deletions} -> {f + 1, ins + additions, del + deletions}
          :skip -> {f, ins, del}
        end
      end)

    {:ok, %{files: files, insertions: insertions, deletions: deletions}}
  end

  # Parse lines like: " lib/mana/commands/diff.ex | 45 ++++++++++"
  # Or: " 3 files changed, 42 insertions(+), 10 deletions(-)"
  defp parse_stat_line(line) do
    cond do
      # Summary line
      Regex.match?(~r/\d+ files? changed/, line) ->
        :skip

      # File line with changes
      Regex.match?(~r/\|.*[+-]/, line) ->
        additions = count_changes(line, "+")
        deletions = count_changes(line, "-")
        {:file, additions, deletions}

      # Binary or other file
      true ->
        {:file, 0, 0}
    end
  end

  defp count_changes(line, char) do
    # Count the change indicators (e.g., +++ or ---)
    case Regex.run(~r/\|.*?(\d+) #{char}{3,}/, line) do
      [_, count] -> String.to_integer(count)
      nil -> 0
    end
  end

  defp format_stats(stats, staged) do
    prefix = if staged, do: "Staged changes", else: "Unstaged changes"

    changes_text =
      cond do
        stats.files == 0 ->
          "No changes."

        stats.insertions == 0 && stats.deletions == 0 ->
          "#{stats.files} file(s) changed"

        stats.deletions == 0 ->
          "#{stats.files} file(s) changed, +#{stats.insertions} lines"

        stats.insertions == 0 ->
          "#{stats.files} file(s) changed, -#{stats.deletions} lines"

        true ->
          "#{stats.files} file(s) changed, +#{stats.insertions}/-#{stats.deletions} lines"
      end

    "#{prefix}: #{changes_text}"
  end

  # Colorization

  defp colorize_diff(diff_text) do
    diff_text
    |> String.split("\n")
    |> Enum.map(&colorize_line/1)
    |> Enum.join("\n")
  end

  # Diff headers (---, +++, @@)
  defp colorize_line("---" <> _ = line), do: "#{@color_header}#{line}#{@color_reset}"
  defp colorize_line("+++" <> _ = line), do: "#{@color_header}#{line}#{@color_reset}"
  defp colorize_line("@@" <> _ = line), do: "#{@color_header}#{line}#{@color_reset}"
  defp colorize_line("diff --git" <> _ = line), do: "#{@color_header}#{line}#{@color_reset}"
  defp colorize_line("index " <> _ = line), do: "#{@color_header}#{line}#{@color_reset}"

  # Additions
  defp colorize_line("+" <> _ = line), do: "#{@color_addition}#{line}#{@color_reset}"

  # Deletions
  defp colorize_line("-" <> _ = line), do: "#{@color_deletion}#{line}#{@color_reset}"

  # Default (no color)
  defp colorize_line(line), do: line
end
