defmodule CodePuppyControl.Text.Diff do
  @moduledoc """
  Unified diff generation in pure Elixir.

  Replaces `code_puppy_core/src/unified_diff.rs` with a pure Elixir
  implementation using `List.myers_difference/2` for the core diff algorithm.

  Generates standard unified diff output (like `diff -u`) compatible
  with the `patch` command.

  ## Examples

      iex> Diff.unified_diff("line 1\\nline 2\\n", "line 1\\nmodified\\nline 2\\n")
      "--- a\\n+++ b\\n@@ -1,3 +1,3 @@\\n line 1\\n-line 2\\n+modified\\n line 3\\n"
  """

  @default_context_lines 3
  @default_from_file "a"
  @default_to_file "b"

  @doc """
  Generate a unified diff between two texts.

  ## Options

    * `:context_lines` - Number of context lines around each change (default: 3)
    * `:from_file` - Label for the original file in the diff header (default: "a")
    * `:to_file` - Label for the new file in the diff header (default: "b")

  ## Returns

  A string containing the unified diff output. Returns an empty string if
  the inputs are identical.
  """
  @spec unified_diff(String.t(), String.t(), keyword()) :: String.t()
  def unified_diff(original, modified, opts \\ []) do
    context_lines = Keyword.get(opts, :context_lines, @default_context_lines)
    from_file = Keyword.get(opts, :from_file, @default_from_file)
    to_file = Keyword.get(opts, :to_file, @default_to_file)

    if original == modified do
      ""
    else
      do_unified_diff(original, modified, context_lines, from_file, to_file)
    end
  end

  defp do_unified_diff(original, modified, context_lines, from_file, to_file) do
    old_lines = split_lines(original)
    new_lines = split_lines(modified)

    diff = List.myers_difference(old_lines, new_lines)

    # Convert diff to annotated segments with positions
    {segments, _, _} =
      Enum.reduce(diff, {[], 0, 0}, fn segment, {acc, old_pos, new_pos} ->
        case segment do
          {:eq, lines} ->
            annotated = {:context, old_pos, new_pos, lines}
            {acc ++ [annotated], old_pos + length(lines), new_pos + length(lines)}

          {:del, lines} ->
            annotated = {:del, old_pos, new_pos, lines}
            {acc ++ [annotated], old_pos + length(lines), new_pos}

          {:ins, lines} ->
            annotated = {:ins, old_pos, new_pos, lines}
            {acc ++ [annotated], old_pos, new_pos + length(lines)}
        end
      end)

    # Group segments into hunks
    hunks = group_into_hunks(segments, context_lines, length(old_lines), length(new_lines))

    if hunks == [] do
      ""
    else
      header = "--- #{from_file}\n+++ #{to_file}\n"
      body = render_hunks(hunks, segments)
      header <> body
    end
  end

  # Split content into lines, preserving the fact that lines don't include \n
  defp split_lines(""), do: []

  defp split_lines(content) do
    String.split(content, "\n", trim: false)
    # Remove the empty string after the final \n
    |> Enum.drop(-1)
  end

  # Group segments into hunks based on context window
  # Two changes should be in the same hunk if the gap between them (in lines)
  # is <= 2 * context_lines
  defp group_into_hunks(segments, context_lines, _old_total, _new_total) do
    # Find all change segments with their old/new line positions
    changes =
      Enum.with_index(segments)
      |> Enum.filter(fn {seg, _idx} ->
        case seg do
          {:del, _, _, _} -> true
          {:ins, _, _, _} -> true
          _ -> false
        end
      end)
      |> Enum.map(fn {seg, idx} ->
        case seg do
          {:del, old_pos, new_pos, lines} ->
            {idx, old_pos, new_pos, length(lines), :del}

          {:ins, old_pos, new_pos, lines} ->
            {idx, old_pos, new_pos, length(lines), :ins}
        end
      end)

    if changes == [] do
      []
    else
      # Build hunks by clustering changes that are close together
      build_hunks_by_proximity(changes, segments, context_lines)
    end
  end

  defp build_hunks_by_proximity(changes, segments, context_lines) do
    max_gap = 2 * context_lines

    # Sort changes by position in the old file
    sorted_changes = Enum.sort_by(changes, fn {_, old_pos, _, _, _} -> old_pos end)

    # Group changes into clusters based on OLD file positions
    # The key insight: we cluster by deletions (which affect old file positions)
    # Insertions at the same old_pos are grouped with their corresponding deletions
    {clusters, current} =
      Enum.reduce(sorted_changes, {[], nil}, fn change, {acc, current} ->
        {idx, old_pos, _new_pos, line_count, type} = change

        case current do
          nil ->
            # First change starts a cluster
            effective_end = if type == :ins, do: old_pos, else: old_pos + line_count
            {acc, {[change], old_pos, effective_end, idx, idx}}

          {changes, cluster_old_start, cluster_old_end, seg_start, seg_end} ->
            # Determine where this change "lands" in the old file
            # For insertions, they land at old_pos (same as any deletion at that position)
            # For deletions, they extend from old_pos to old_pos + line_count
            change_start = old_pos
            change_end = if type == :ins, do: old_pos, else: old_pos + line_count

            # Calculate gap from the end of the cluster to the start of this change
            gap = change_start - cluster_old_end

            if gap <= max_gap do
              # Merge into current cluster
              new_changes = changes ++ [change]
              new_end = max(cluster_old_end, change_end)
              {acc, {new_changes, cluster_old_start, new_end, seg_start, idx}}
            else
              # Start new cluster
              {acc ++ [{changes, cluster_old_start, cluster_old_end, seg_start, seg_end}],
               {[change], change_start, change_end, idx, idx}}
            end
        end
      end)

    # Add the last cluster
    clusters =
      case current do
        nil -> clusters
        last -> clusters ++ [last]
      end

    # Convert clusters to hunk ranges with proper context
    Enum.map(clusters, fn {change_list, _old_start, _old_end, seg_start, seg_end} ->
      # Expand segment range to include context_lines on each side
      hunk_start = max(0, seg_start)
      hunk_end = min(length(segments) - 1, seg_end)

      # Now expand to include context lines
      {final_start, final_end} = expand_for_context(hunk_start, hunk_end, segments, context_lines)

      # Collect change indices in this hunk
      change_indices = Enum.map(change_list, fn {idx, _, _, _, _} -> idx end)

      {final_start, final_end, change_indices}
    end)
  end

  # Expand hunk boundaries to include context_lines on each side
  defp expand_for_context(start_idx, end_idx, segments, context_lines) do
    # Expand start to include context_lines
    new_start = find_start_with_context(start_idx, segments, context_lines)

    # Expand end to include context_lines
    new_end = find_end_with_context(end_idx, segments, context_lines, length(segments) - 1)

    {new_start, new_end}
  end

  defp find_start_with_context(idx, segments, context_lines) do
    target = context_lines

    {result, _} =
      Enum.reduce_while((idx - 1)..0//-1, {idx, 0}, fn i, {current, count} ->
        if i < 0 do
          {:halt, {current, count}}
        else
          case Enum.at(segments, i) do
            {:context, _, _, lines} ->
              lines_count = length(lines)

              if count + lines_count >= target do
                {:halt, {i, count + lines_count}}
              else
                {:cont, {i, count + lines_count}}
              end

            _ ->
              {:cont, {i, count}}
          end
        end
      end)

    max(result, 0)
  end

  defp find_end_with_context(idx, segments, context_lines, max_idx) do
    target = context_lines

    # Start from idx (not idx+1) to include current segment if it's context
    {result, _} =
      Enum.reduce_while(idx..max_idx, {idx, 0}, fn i, {current, count} ->
        if i > max_idx do
          {:halt, {current, count}}
        else
          case Enum.at(segments, i) do
            {:context, _, _, lines} ->
              lines_count = length(lines)

              if count + lines_count >= target do
                {:halt, {i, count + lines_count}}
              else
                {:cont, {i, count + lines_count}}
              end

            _ ->
              {:cont, {i, count}}
          end
        end
      end)

    min(result, max_idx)
  end

  defp render_hunks(hunks, segments) do
    hunks
    |> Enum.map(fn {start_idx, end_idx, _changes} ->
      render_hunk(segments, start_idx, end_idx)
    end)
    |> Enum.join("")
  end

  defp render_hunk(segments, start_idx, end_idx) do
    # Calculate line numbers for hunk header
    {old_start, old_count, new_start, new_count} =
      calculate_hunk_stats(segments, start_idx, end_idx)

    header = format_hunk_header(old_start, old_count, new_start, new_count)

    body =
      for i <- start_idx..end_idx do
        render_segment(Enum.at(segments, i))
      end
      |> Enum.join("")

    header <> body
  end

  # Format hunk header with proper handling for empty files
  # Standard unified diff format (Rust similar crate style):
  # - @@ -1,3 +1,3 @@ for normal case
  # - @@ -0,0 +1,2 @@ for adding to empty file
  # - @@ -1,2 +0,0 @@ for deleting all
  # - @@ -1 +1 @@ for single line changes (simplified form)
  defp format_hunk_header(old_start, old_count, new_start, new_count) do
    # Calculate 1-indexed positions
    old_1idx = old_start + 1
    new_1idx = new_start + 1

    # Build display strings matching the Rust similar crate format
    old_display =
      if old_count == 0 do
        "#{old_1idx - 1},0"
      else
        "#{old_1idx},#{old_count}"
      end

    new_display =
      if new_count == 0 do
        "#{new_1idx - 1},0"
      else
        "#{new_1idx},#{new_count}"
      end

    "@@ -#{old_display} +#{new_display} @@\n"
  end

  defp calculate_hunk_stats(segments, start_idx, end_idx) do
    # Find the first old and new line numbers in the hunk
    segs_in_hunk =
      start_idx..end_idx
      |> Enum.map(&Enum.at(segments, &1))
      |> Enum.filter(fn x -> x != nil end)

    # Find first old line position (for context or del)
    old_start =
      segs_in_hunk
      |> Enum.find_value(0, fn seg ->
        case seg do
          {:context, pos, _, _} -> pos
          {:del, pos, _, _} -> pos
          _ -> nil
        end
      end)

    # Find first new line position (for context or ins)
    new_start =
      segs_in_hunk
      |> Enum.find_value(0, fn seg ->
        case seg do
          {:context, _, pos, _} -> pos
          {:ins, _, pos, _} -> pos
          _ -> nil
        end
      end)

    # Count lines in the hunk
    {old_count, new_count} =
      Enum.reduce(segs_in_hunk, {0, 0}, fn seg, {old_acc, new_acc} ->
        case seg do
          {:context, _, _, lines} -> {old_acc + length(lines), new_acc + length(lines)}
          {:del, _, _, lines} -> {old_acc + length(lines), new_acc}
          {:ins, _, _, lines} -> {old_acc, new_acc + length(lines)}
        end
      end)

    {old_start, old_count, new_start, new_count}
  end

  defp render_segment({:context, _, _, lines}) do
    Enum.map_join(lines, "\n", &" #{&1}") <> "\n"
  end

  defp render_segment({:del, _, _, lines}) do
    Enum.map_join(lines, "\n", &"-#{&1}") <> "\n"
  end

  defp render_segment({:ins, _, _, lines}) do
    Enum.map_join(lines, "\n", &"+#{&1}") <> "\n"
  end
end
