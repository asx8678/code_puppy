defmodule Mana.Tools.FileOps.ListFiles do
  @moduledoc "Tool for listing files in a directory"

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.IgnorePatterns
  alias Mana.Tools.SafePath

  @impl true
  def name, do: "list_files"

  @impl true
  def description, do: "List files in a directory (recursive)"

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        directory: %{
          type: "string",
          default: ".",
          description: "Directory to list"
        },
        recursive: %{
          type: "boolean",
          default: true,
          description: "Recursive listing"
        }
      },
      required: []
    }
  end

  @impl true
  def execute(args) do
    dir = Map.get(args, "directory", ".")
    recursive = Map.get(args, "recursive", true)

    # Validate path safety
    with {:ok, cwd} <- SafePath.current_working_dir(),
         {:ok, safe_dir} <- SafePath.validate(dir, cwd) do
      case list_files(safe_dir, recursive) do
        {:ok, files} -> {:ok, %{"files" => files, "count" => length(files)}}
        error -> error
      end
    end
  end

  defp list_files(dir, recursive) do
    case File.ls(dir) do
      {:ok, entries} ->
        files =
          entries
          |> Enum.map(&Path.join(dir, &1))
          |> Enum.reject(&IgnorePatterns.ignore_path?/1)
          |> Enum.flat_map(&expand_path(&1, recursive))

        {:ok, files}

      {:error, reason} ->
        {:error, "Failed to list #{dir}: #{reason}"}
    end
  end

  defp expand_path(path, recursive) do
    cond do
      File.dir?(path) and recursive ->
        case list_files(path, true) do
          {:ok, sub_files} -> [path | sub_files]
          _ -> [path]
        end

      File.dir?(path) ->
        [path]

      true ->
        [path]
    end
  end
end

defmodule Mana.Tools.FileOps.ReadFile do
  @moduledoc "Tool for reading file contents with optional line range"

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.SafePath

  @impl true
  def name, do: "read_file"

  @impl true
  def description, do: "Read file contents with optional line range"

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        file_path: %{
          type: "string",
          required: true,
          description: "Path to file"
        },
        start_line: %{
          type: "integer",
          description: "Start line (1-indexed)"
        },
        num_lines: %{
          type: "integer",
          description: "Number of lines to read"
        }
      },
      required: ["file_path"]
    }
  end

  @impl true
  def execute(args) do
    file_path = Map.get(args, "file_path")
    start_line = Map.get(args, "start_line")
    num_lines = Map.get(args, "num_lines")

    # Validate path safety
    with {:ok, cwd} <- SafePath.current_working_dir(),
         {:ok, safe_path} <- SafePath.validate(file_path, cwd) do
      case File.read(safe_path) do
        {:ok, content} ->
          result = extract_content(content, start_line, num_lines)
          total_lines = content |> String.split("\n") |> length()

          {:ok,
           %{
             "content" => result,
             "file_path" => safe_path,
             "total_lines" => total_lines
           }}

        {:error, reason} ->
          {:error, "Failed to read #{safe_path}: #{reason}"}
      end
    end
  end

  defp extract_content(content, nil, _num_lines), do: content

  defp extract_content(content, start_line, num_lines) do
    lines = String.split(content, "\n")
    dropped = Enum.drop(lines, max(0, start_line - 1))

    if num_lines do
      dropped |> Enum.take(num_lines) |> Enum.join("\n")
    else
      Enum.join(dropped, "\n")
    end
  end
end

defmodule Mana.Tools.FileOps.Grep do
  @moduledoc "Tool for searching file contents using ripgrep"

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.SafePath

  @impl true
  def name, do: "grep"

  @impl true
  def description, do: "Search file contents using ripgrep"

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        search_string: %{
          type: "string",
          required: true,
          description: "Search pattern"
        },
        directory: %{
          type: "string",
          default: ".",
          description: "Directory to search"
        }
      },
      required: ["search_string"]
    }
  end

  @impl true
  def execute(args) do
    pattern = Map.get(args, "search_string")
    dir = Map.get(args, "directory", ".")

    # Validate path safety
    with {:ok, cwd} <- SafePath.current_working_dir(),
         {:ok, safe_dir} <- SafePath.validate(dir, cwd) do
      case System.cmd("rg", ["--json", pattern, safe_dir], stderr_to_stdout: true) do
        {output, 0} ->
          matches = parse_grep_output(output)
          {:ok, %{"matches" => matches, "count" => length(matches)}}

        {output, 1} ->
          # Exit code 1 means no matches found (not an error)
          if String.contains?(output, "No files were searched") do
            {:ok, %{"matches" => [], "count" => 0}}
          else
            # Check if output contains matches (some ripgrep versions return 1 with matches)
            matches = parse_grep_output(output)
            {:ok, %{"matches" => matches, "count" => length(matches)}}
          end

        {output, _} ->
          if String.contains?(output, "No files were searched") do
            {:ok, %{"matches" => [], "count" => 0}}
          else
            {:error, "grep failed: #{output}"}
          end
      end
    end
  end

  defp parse_grep_output(output) do
    output
    |> String.split("\n")
    |> Enum.filter(&String.starts_with?(&1, "{"))
    |> Enum.map(&decode_match/1)
    |> Enum.reject(&is_nil/1)
  end

  defp decode_match(line) do
    case Jason.decode(line) do
      {:ok, %{"type" => "match", "data" => data}} ->
        %{
          "file" => data["path"]["text"],
          "line" => data["line_number"],
          "text" => data["lines"]["text"]
        }

      _ ->
        nil
    end
  end
end
