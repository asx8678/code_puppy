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

  alias CodePuppyControl.FileOps.Security
  alias CodePuppyControl.Tools.FileModifications.{SafeWrite, DiffEmitter}

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

      SafeWrite.symlink?(file_path) ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "Refusing to delete symlink (security: symlink attack prevention)",
           changed: false
         }}

      true ->
        case File.read(file_path) do
          {:ok, original_content} ->
            # Summary-style diff (avoids full content in diff for large files)
            line_count = original_content |> String.split("\n") |> length()
            file_size = byte_size(original_content)

            diff =
              "--- a/#{Path.basename(file_path)}\n+++ /dev/null\n" <>
                "@@ -1,#{line_count} +0,0 @@\n" <>
                "< File deleted: #{line_count} lines, #{file_size} bytes >\n"

            case File.rm(file_path) do
              :ok ->
                # Emit diff for UI display
                DiffEmitter.emit_diff(file_path, :delete, diff)

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
