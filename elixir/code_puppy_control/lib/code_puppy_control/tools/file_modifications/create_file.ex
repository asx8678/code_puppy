defmodule CodePuppyControl.Tools.FileModifications.CreateFile do
  @moduledoc """
  Tool for creating new files or overwriting existing ones.

  Creates a file at the specified path with the provided content.
  When `overwrite` is false (default), returns an error if the file exists.
  When `overwrite` is true, replaces the existing file content.

  ## Security

  - Path is validated via `FileOps.Security.validate_path/2` to block sensitive paths
  - Symlink-safe writes via `SafeWrite` (O_NOFOLLOW equivalent)
  - BOM handling: strips BOM for matching, restores on write
  - Permission check integrates with `PolicyEngine`

  Port of `code_puppy/tools/file_modifications.py:_write_to_file`.
  """

  use CodePuppyControl.Tool

  require Logger

  alias CodePuppyControl.{FileOps.Security, Text.Diff, Text.EOL}
  alias CodePuppyControl.Tools.FileModifications.{SafeWrite, DiffEmitter, Validation}

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
            # Strip BOM for matching, track for restoration
            {original_no_bom, bom} = EOL.strip_bom(original)
            # Strip LLM-hallucinated blank lines
            content_stripped = EOL.strip_added_blank_lines(original_no_bom, content)
            # Restore BOM on write
            final_content = EOL.restore_bom(content_stripped, bom)
            write_and_report(file_path, final_content, original_no_bom, :modify, bom)

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
        # New file creation — no BOM to preserve
        write_and_report(file_path, content, "", :create, nil)
    end
  end

  defp write_and_report(file_path, content, original, operation, _bom) do
    case SafeWrite.safe_write(file_path, content) do
      :ok ->
        diff =
          Diff.unified_diff(original, content,
            from_file: if(operation == :create, do: "/dev/null", else: "a/#{Path.basename(file_path)}"),
            to_file: "b/#{Path.basename(file_path)}"
          )

        # Emit diff for UI display
        DiffEmitter.emit_diff(file_path, operation, diff,
          new_content: content
        )

        result = %{
          success: true,
          path: file_path,
          message: "File #{(operation == :create && "created") || "updated"} successfully",
          changed: original != content,
          diff: diff
        }

        # Post-edit syntax validation (advisory only)
        result = Validation.maybe_attach_warning(result, file_path)

        {:ok, result}

      {:error, :symlink_detected} ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "Refusing to write to symlink (security: symlink attack prevention)",
           changed: false
         }}

      {:error, reason} when is_binary(reason) ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: reason,
           changed: false
         }}

      {:error, reason} ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "Failed to write file: #{inspect(reason)}",
           changed: false
         }}
    end
  end
end
