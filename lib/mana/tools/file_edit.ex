defmodule Mana.Tools.FileEdit.CreateFile do
  @moduledoc "Tool for creating a new file with content"

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.SafePath

  @impl true
  def name, do: "create_file"

  @impl true
  def description, do: "Create a new file with content"

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        file_path: %{
          type: "string",
          required: true,
          description: "Path to file to create"
        },
        content: %{
          type: "string",
          required: true,
          description: "Content to write to file"
        }
      },
      required: ["file_path", "content"]
    }
  end

  @impl true
  def execute(args) do
    path = Map.get(args, "file_path")
    content = Map.get(args, "content")

    with {:ok, cwd} <- SafePath.current_working_dir(),
         :ok <- ensure_parent_directory(path, cwd),
         :ok <- SafePath.safe_write(path, content, cwd) do
      {:ok, %{"created" => path, "size" => byte_size(content)}}
    end
  end

  # Create parent directory before validate + safe_write.
  # We do this before validation because validate will fail with :enoent
  # if the parent directory doesn't exist. The safe_write call handles
  # the actual atomic write with TOCTOU protection.
  defp ensure_parent_directory(path, cwd) do
    expanded =
      if Path.type(path) == :relative do
        Path.expand(path, cwd)
      else
        Path.expand(path)
      end

    dir = Path.dirname(expanded)

    case File.mkdir_p(dir) do
      :ok -> :ok
      {:error, reason} -> {:error, "Failed to create directory #{dir}: #{reason}"}
    end
  end
end

defmodule Mana.Tools.FileEdit.ReplaceInFile do
  @moduledoc "Tool for replacing text in a file"

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.SafePath

  @impl true
  def name, do: "replace_in_file"

  @impl true
  def description, do: "Replace text in a file"

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
        old_string: %{
          type: "string",
          required: true,
          description: "Text to replace"
        },
        new_string: %{
          type: "string",
          required: true,
          description: "Replacement text"
        }
      },
      required: ["file_path", "old_string", "new_string"]
    }
  end

  @impl true
  def execute(args) do
    path = Map.get(args, "file_path")
    old = Map.get(args, "old_string")
    new = Map.get(args, "new_string")

    with {:ok, cwd} <- SafePath.current_working_dir(),
         {:ok, _new_content} <- safe_transform_with_replace(path, old, new, cwd) do
      diff = generate_diff(old, new)
      {:ok, %{"replaced" => path, "diff" => diff}}
    end
  end

  # Uses SafePath.safe_transform with a custom transform function that
  # performs the string replacement. The safe_transform internally uses
  # safe_write which provides TOCTOU protection via atomic rename.
  defp safe_transform_with_replace(path, old, new, cwd) do
    SafePath.safe_transform(
      path,
      fn content ->
        if String.contains?(content, old) do
          String.replace(content, old, new, global: false)
        else
          raise ArgumentError, "String not found in file"
        end
      end,
      cwd
    )
  rescue
    ArgumentError -> {:error, "String not found in #{path}"}
  end

  defp generate_diff(old, new) do
    old_lines = String.split(old, "\n")
    new_lines = String.split(new, "\n")

    removed = Enum.map(old_lines, fn line -> "- #{line}" end)
    added = Enum.map(new_lines, fn line -> "+ #{line}" end)

    Enum.join(removed ++ added, "\n")
  end
end

defmodule Mana.Tools.FileEdit.DeleteFile do
  @moduledoc "Tool for deleting a file"

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.SafePath

  @impl true
  def name, do: "delete_file"

  @impl true
  def description, do: "Delete a file"

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        file_path: %{
          type: "string",
          required: true,
          description: "Path to file to delete"
        }
      },
      required: ["file_path"]
    }
  end

  @impl true
  def execute(args) do
    path = Map.get(args, "file_path")

    # Validate path safety
    with {:ok, cwd} <- SafePath.current_working_dir(),
         {:ok, safe_path} <- SafePath.validate(path, cwd) do
      case File.rm(safe_path) do
        :ok -> {:ok, %{"deleted" => safe_path}}
        {:error, reason} -> {:error, "Failed to delete #{safe_path}: #{reason}"}
      end
    end
  end
end
