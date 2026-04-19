defmodule CodePuppyControl.Tools.FileModifications.DeleteFile do
  @moduledoc """
  Tool for safely deleting files with comprehensive logging and diff generation.

  Shows exactly what content was removed via diff output.

  ## Security

  - Path validated via `FileOps.Security` to block sensitive paths
  - Never deletes directories (only regular files)
  - Permission check integrates with `PolicyEngine`
  """

  use CodePuppyControl.Tool

  require Logger

  alias CodePuppyControl.{FileOps.Security, Text.Diff}

  @impl true
  def name, do: :delete_file

  @impl true
  def description do
    "Safely delete a file with comprehensive logging and diff generation. " <>
      "Shows exactly what content was removed."
  end

  @impl true
  def parameters do
    %{
      "type" => "object",
      "properties" => %{
        "file_path" => %{
          "type" => "string",
          "description" => "Path to the file to delete"
        }
      },
      "required" => ["file_path"]
    }
  end

  @impl true
  def permission_check(args, _context) do
    file_path = Map.get(args, "file_path", "")

    case Security.validate_path(file_path, "delete") do
      {:ok, _} -> :ok
      {:error, reason} -> {:deny, reason}
    end
  end

  @impl true
  def invoke(args, _context) do
    file_path = Map.get(args, "file_path", "")

    with {:ok, expanded_path} <- Security.validate_path(file_path, "delete") do
      do_delete(expanded_path)
    end
  end

  defp do_delete(file_path) do
    cond do
      not File.exists?(file_path) ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "File not found",
           changed: false
         }}

      File.dir?(file_path) ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "Cannot delete directory — only files are supported",
           changed: false
         }}

      true ->
        case File.read(file_path) do
          {:ok, original_content} ->
            diff =
              Diff.unified_diff(original_content, "",
                from_file: "a/#{Path.basename(file_path)}",
                to_file: "b/#{Path.basename(file_path)}"
              )

            case File.rm(file_path) do
              :ok ->
                {:ok,
                 %{
                   success: true,
                   path: file_path,
                   message: "File deleted successfully",
                   changed: true,
                   diff: diff,
                   deleted_content: original_content
                 }}

              {:error, reason} ->
                {:error,
                 %{
                   success: false,
                   path: file_path,
                   message: "Failed to delete file: #{:file.format_error(reason)}",
                   changed: false
                 }}
            end

          {:error, reason} ->
            {:error,
             %{
               success: false,
               path: file_path,
               message: "Failed to read file before deletion: #{:file.format_error(reason)}",
               changed: false
             }}
        end
    end
  end
end
