defmodule CodePuppyControl.Tools.FileModifications.CreateFile do
  @moduledoc """
  Tool for creating new files or overwriting existing ones.

  Creates a file at the specified path with the provided content.
  When `overwrite` is false (default), returns an error if the file exists.
  When `overwrite` is true, replaces the existing file content.

  ## Security

  - Path is validated via `FileOps.Security.validate_path/2` to block sensitive paths
  - Permission check integrates with `PolicyEngine`
  """

  use CodePuppyControl.Tool

  require Logger

  alias CodePuppyControl.{FileOps.Security, Text.Diff}

  @impl true
  def name, do: :create_file

  @impl true
  def description do
    "Create a new file or overwrite an existing one with the provided content."
  end

  @impl true
  def parameters do
    %{
      "type" => "object",
      "properties" => %{
        "file_path" => %{
          "type" => "string",
          "description" => "Path to the file to create (relative or absolute)"
        },
        "content" => %{
          "type" => "string",
          "description" => "Content to write to the file"
        },
        "overwrite" => %{
          "type" => "boolean",
          "description" => "If true, overwrite existing file. Default: false"
        }
      },
      "required" => ["file_path", "content"]
    }
  end

  @impl true
  def permission_check(args, _context) do
    file_path = Map.get(args, "file_path", "")

    case Security.validate_path(file_path, "create") do
      {:ok, _} -> :ok
      {:error, reason} -> {:deny, reason}
    end
  end

  @impl true
  def invoke(args, _context) do
    file_path = Map.get(args, "file_path", "")
    content = Map.get(args, "content", "")
    overwrite = Map.get(args, "overwrite", false)

    with {:ok, expanded_path} <- Security.validate_path(file_path, "create") do
      do_create(expanded_path, content, overwrite)
    end
  end

  defp do_create(file_path, content, overwrite) do
    cond do
      File.exists?(file_path) and not overwrite ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "File already exists. Set overwrite=true to replace.",
           changed: false
         }}

      File.exists?(file_path) and overwrite ->
        case File.read(file_path) do
          {:ok, original} ->
            write_and_report(file_path, content, original, :modify)

          {:error, reason} ->
            {:error,
             %{
               success: false,
               path: file_path,
               message: "Failed to read existing file: #{:file.format_error(reason)}",
               changed: false
             }}
        end

      true ->
        # New file creation
        write_and_report(file_path, content, "", :create)
    end
  end

  defp write_and_report(file_path, content, original, operation) do
    # Ensure parent directory exists
    parent_dir = Path.dirname(file_path)

    case File.mkdir_p(parent_dir) do
      :ok ->
        case File.write(file_path, content) do
          :ok ->
            diff =
              Diff.unified_diff(original, content,
                from_file: "a/#{Path.basename(file_path)}",
                to_file: "b/#{Path.basename(file_path)}"
              )

            {:ok,
             %{
               success: true,
               path: file_path,
               message: "File #{(operation == :create && "created") || "updated"} successfully",
               changed: original != content,
               diff: diff
             }}

          {:error, reason} ->
            {:error,
             %{
               success: false,
               path: file_path,
               message: "Failed to write file: #{:file.format_error(reason)}",
               changed: false
             }}
        end

      {:error, reason} ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "Failed to create parent directory: #{:file.format_error(reason)}",
           changed: false
         }}
    end
  end
end
