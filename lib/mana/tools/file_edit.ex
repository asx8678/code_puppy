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

    # Validate path safety
    with {:ok, cwd} <- SafePath.current_working_dir(),
         {:ok, safe_path} <- SafePath.validate(path, cwd),
         :ok <- ensure_directory(safe_path),
         :ok <- write_file(safe_path, content) do
      {:ok, %{"created" => safe_path, "size" => byte_size(content)}}
    end
  end

  defp ensure_directory(safe_path) do
    dir = Path.dirname(safe_path)

    case File.mkdir_p(dir) do
      :ok -> :ok
      {:error, reason} -> {:error, "Failed to create directory #{dir}: #{reason}"}
    end
  end

  defp write_file(safe_path, content) do
    case File.write(safe_path, content) do
      :ok -> :ok
      {:error, reason} -> {:error, "Failed to create #{safe_path}: #{reason}"}
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

    # Validate path safety
    with {:ok, cwd} <- SafePath.current_working_dir(),
         {:ok, safe_path} <- SafePath.validate(path, cwd),
         {:ok, content} <- read_file(safe_path) do
      perform_replacement(safe_path, content, old, new)
    end
  end

  defp read_file(safe_path) do
    case File.read(safe_path) do
      {:ok, content} -> {:ok, content}
      {:error, reason} -> {:error, "Failed to read #{safe_path}: #{reason}"}
    end
  end

  defp perform_replacement(safe_path, content, old, new) do
    if String.contains?(content, old) do
      new_content = String.replace(content, old, new, global: false)
      File.write!(safe_path, new_content)
      diff = generate_diff(old, new)
      {:ok, %{"replaced" => safe_path, "diff" => diff}}
    else
      {:error, "String not found in #{safe_path}"}
    end
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
