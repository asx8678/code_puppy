defmodule CodePuppyControl.Tools.FileModifications.ReplaceInFile do
  @moduledoc """
  Tool for applying targeted text replacements to existing files.

  Each replacement specifies an `old_str` to find and a `new_str` to replace it with.
  Replacements are applied sequentially — each subsequent replacement sees the result
  of the previous one.

  Uses `CodePuppyControl.Text.ReplaceEngine` for exact/fuzzy matching with a
  Jaro-Winkler threshold of 0.95.

  ## Security

  - Path validated via `FileOps.Security`
  - Permission check via `PolicyEngine`

  ## Important: replacements is a LIST

  The `replacements` argument MUST be a list of maps, each with `old_str` and `new_str`.
  This is validated by the JSON schema before invocation.
  """

  use CodePuppyControl.Tool

  require Logger

  alias CodePuppyControl.{FileOps.Security, Text.ReplaceEngine}

  @impl true
  def name, do: :replace_in_file

  @impl true
  def description do
    "Apply targeted text replacements to an existing file. " <>
      "Each replacement specifies an old_str to find and a new_str to replace it with. " <>
      "Replacements are applied sequentially. Prefer this over full file rewrites."
  end

  @impl true
  def parameters do
    %{
      "type" => "object",
      "properties" => %{
        "file_path" => %{
          "type" => "string",
          "description" => "Path to the file to modify"
        },
        "replacements" => %{
          "type" => "array",
          "description" =>
            "List of replacement objects. Each must have old_str and new_str. " <>
              "Applied sequentially — each replacement sees the result of the previous.",
          "items" => %{
            "type" => "object",
            "properties" => %{
              "old_str" => %{
                "type" => "string",
                "description" => "Text to find (exact match first, then fuzzy)"
              },
              "new_str" => %{
                "type" => "string",
                "description" => "Text to replace with"
              }
            },
            "required" => ["old_str", "new_str"]
          },
          "minItems" => 1
        }
      },
      "required" => ["file_path", "replacements"]
    }
  end

  @impl true
  def permission_check(args, _context) do
    file_path = Map.get(args, "file_path", "")

    case Security.validate_path(file_path, "replace text in") do
      {:ok, _} -> :ok
      {:error, reason} -> {:deny, reason}
    end
  end

  @impl true
  def invoke(args, _context) do
    file_path = Map.get(args, "file_path", "")
    raw_replacements = Map.get(args, "replacements", [])

    with {:ok, expanded_path} <- Security.validate_path(file_path, "replace text in"),
         {:ok, replacements} <- validate_replacements(raw_replacements) do
      do_replace(expanded_path, replacements)
    end
  end

  defp validate_replacements(replacements) when is_list(replacements) do
    validated =
      Enum.reduce_while(replacements, {:ok, []}, fn item, {:ok, acc} ->
        case validate_replacement_item(item) do
          {:ok, tuple} -> {:cont, {:ok, [tuple | acc]}}
          {:error, reason} -> {:halt, {:error, reason}}
        end
      end)

    case validated do
      {:ok, tuples} -> {:ok, Enum.reverse(tuples)}
      {:error, reason} -> {:error, reason}
    end
  end

  defp validate_replacements(_other) do
    {:error, "replacements must be a list"}
  end

  defp validate_replacement_item(%{"old_str" => old, "new_str" => new})
       when is_binary(old) and is_binary(new) do
    {:ok, {old, new}}
  end

  defp validate_replacement_item(item) when is_map(item) do
    {:error, "Each replacement must have string old_str and new_str keys, got: #{inspect(item)}"}
  end

  defp validate_replacement_item(other) do
    {:error, "Each replacement must be a map, got: #{inspect(other)}"}
  end

  defp do_replace(file_path, replacements) do
    case File.read(file_path) do
      {:ok, content} ->
        case ReplaceEngine.replace_in_content(content, replacements) do
          {:ok, %{modified: modified, diff: diff}} ->
            if modified == content do
              {:ok,
               %{
                 success: true,
                 path: file_path,
                 message: "No changes needed (content already matches)",
                 changed: false,
                 diff: ""
               }}
            else
              case File.write(file_path, modified) do
                :ok ->
                  {:ok,
                   %{
                     success: true,
                     path: file_path,
                     message: "Replacements applied successfully",
                     changed: true,
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
            end

          {:error, %{reason: reason, jw_score: score}} ->
            {:error,
             %{
               success: false,
               path: file_path,
               message: "Replacement failed: #{reason}",
               jw_score: score,
               changed: false
             }}
        end

      {:error, :enoent} ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "File not found",
           changed: false
         }}

      {:error, reason} ->
        {:error,
         %{
           success: false,
           path: file_path,
           message: "Failed to read file: #{:file.format_error(reason)}",
           changed: false
         }}
    end
  end
end
