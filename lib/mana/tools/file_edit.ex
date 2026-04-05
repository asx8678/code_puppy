defmodule Mana.Tools.FileEdit.CreateFile do
  @moduledoc "Tool for creating a new file with content"

  @behaviour Mana.Tools.Behaviour

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

    dir = Path.dirname(path)

    case File.mkdir_p(dir) do
      :ok ->
        case File.write(path, content) do
          :ok -> {:ok, %{"created" => path, "size" => byte_size(content)}}
          {:error, reason} -> {:error, "Failed to create #{path}: #{reason}"}
        end

      {:error, reason} ->
        {:error, "Failed to create directory #{dir}: #{reason}"}
    end
  end
end

defmodule Mana.Tools.FileEdit.ReplaceInFile do
  @moduledoc "Tool for replacing text in a file"

  @behaviour Mana.Tools.Behaviour

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

    case File.read(path) do
      {:ok, content} ->
        if String.contains?(content, old) do
          new_content = String.replace(content, old, new, global: false)
          File.write!(path, new_content)
          diff = generate_diff(old, new)
          {:ok, %{"replaced" => path, "diff" => diff}}
        else
          {:error, "String not found in #{path}"}
        end

      {:error, reason} ->
        {:error, "Failed to read #{path}: #{reason}"}
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

    case File.rm(path) do
      :ok -> {:ok, %{"deleted" => path}}
      {:error, reason} -> {:error, "Failed to delete #{path}: #{reason}"}
    end
  end
end
