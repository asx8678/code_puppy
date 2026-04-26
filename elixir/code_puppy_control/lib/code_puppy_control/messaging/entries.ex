defmodule CodePuppyControl.Messaging.Entries do
  @moduledoc """
  Nested entry model constructors for Agent→UI messages.

  Provides validated constructors for the structured entry types that appear
  inside list fields of message families. Each constructor enforces
  Pydantic-style `extra='forbid'` semantics, rejecting unknown keys.

  Mirrors the Python entry models in `code_puppy/messaging/messages.py`:

  | Python class  | Elixir function       |
  |--------------|----------------------|
  | `FileEntry`  | `file_entry/1`       |
  | `GrepMatch`  | `grep_match/1`       |
  | `DiffLine`   | `diff_line/1`        |
  | `SkillEntry` | `skill_entry/1`      |

  All constructors return `{:ok, map}` or `{:error, reason}` — never raise.
  """

  alias CodePuppyControl.Messaging.Validation

  # ── FileEntry ──────────────────────────────────────────────────────────────

  @file_entry_allowed_keys MapSet.new(~w(path type size depth))

  @doc """
  Builds a validated FileEntry map.

  ## Required fields

  - `"path"` — string, file or directory path
  - `"type"` — literal `"file"` or `"dir"`
  - `"size"` — integer ≥ -1 (0 for dirs, -1 for unknown)
  - `"depth"` — integer ≥ 0 (nesting depth from listing root)

  ## Extra keys

  Rejected with `{:error, {:extra_fields_not_allowed, keys}}`.
  """
  @spec file_entry(map()) :: {:ok, map()} | {:error, term()}
  def file_entry(fields) when is_map(fields) do
    with :ok <- Validation.reject_extra_keys(fields, @file_entry_allowed_keys),
         {:ok, path} <- Validation.require_string(fields, "path"),
         {:ok, type} <- Validation.require_literal(fields, "type", ~w(file dir)),
         {:ok, size} <- Validation.require_integer(fields, "size", min: -1),
         {:ok, depth} <- Validation.require_integer(fields, "depth", min: 0) do
      {:ok, %{"path" => path, "type" => type, "size" => size, "depth" => depth}}
    end
  end

  def file_entry(other), do: {:error, {:not_a_map, other}}

  # ── GrepMatch ─────────────────────────────────────────────────────────────

  @grep_match_allowed_keys MapSet.new(~w(file_path line_number line_content))

  @doc """
  Builds a validated GrepMatch map.

  ## Required fields

  - `"file_path"` — string, path to matched file
  - `"line_number"` — integer ≥ 1 (1-based)
  - `"line_content"` — string, full line content with match

  ## Extra keys

  Rejected with `{:error, {:extra_fields_not_allowed, keys}}`.
  """
  @spec grep_match(map()) :: {:ok, map()} | {:error, term()}
  def grep_match(fields) when is_map(fields) do
    with :ok <- Validation.reject_extra_keys(fields, @grep_match_allowed_keys),
         {:ok, file_path} <- Validation.require_string(fields, "file_path"),
         {:ok, line_number} <- Validation.require_integer(fields, "line_number", min: 1),
         {:ok, line_content} <- Validation.require_string(fields, "line_content") do
      {:ok,
       %{
         "file_path" => file_path,
         "line_number" => line_number,
         "line_content" => line_content
       }}
    end
  end

  def grep_match(other), do: {:error, {:not_a_map, other}}

  # ── DiffLine ───────────────────────────────────────────────────────────────

  @diff_line_allowed_keys MapSet.new(~w(line_number type content))
  @diff_line_types ~w(add remove context)

  @doc """
  Builds a validated DiffLine map.

  ## Required fields

  - `"line_number"` — integer ≥ 0
  - `"type"` — literal `"add"`, `"remove"`, or `"context"`
  - `"content"` — string, the line content

  ## Extra keys

  Rejected with `{:error, {:extra_fields_not_allowed, keys}}`.
  """
  @spec diff_line(map()) :: {:ok, map()} | {:error, term()}
  def diff_line(fields) when is_map(fields) do
    with :ok <- Validation.reject_extra_keys(fields, @diff_line_allowed_keys),
         {:ok, line_number} <- Validation.require_integer(fields, "line_number", min: 0),
         {:ok, type} <- Validation.require_literal(fields, "type", @diff_line_types),
         {:ok, content} <- Validation.require_string(fields, "content") do
      {:ok, %{"line_number" => line_number, "type" => type, "content" => content}}
    end
  end

  def diff_line(other), do: {:error, {:not_a_map, other}}

  # ── SkillEntry ────────────────────────────────────────────────────────────

  @skill_entry_allowed_keys MapSet.new(~w(name description path tags enabled))

  @doc """
  Builds a validated SkillEntry map.

  ## Required fields

  - `"name"` — string, skill name
  - `"description"` — string, skill description
  - `"path"` — string, path to skill directory

  ## Optional fields with defaults

  - `"tags"` — list of strings (default: `[]`)
  - `"enabled"` — boolean (default: `true`)

  ## Extra keys

  Rejected with `{:error, {:extra_fields_not_allowed, keys}}`.
  """
  @spec skill_entry(map()) :: {:ok, map()} | {:error, term()}
  def skill_entry(fields) when is_map(fields) do
    with :ok <- Validation.reject_extra_keys(fields, @skill_entry_allowed_keys),
         {:ok, name} <- Validation.require_string(fields, "name"),
         {:ok, description} <- Validation.require_string(fields, "description"),
         {:ok, path} <- Validation.require_string(fields, "path"),
         {:ok, tags} <- validate_tags(fields),
         {:ok, enabled} <- Validation.optional_boolean(fields, "enabled", true) do
      {:ok,
       %{
         "name" => name,
         "description" => description,
         "path" => path,
         "tags" => tags,
         "enabled" => enabled
       }}
    end
  end

  def skill_entry(other), do: {:error, {:not_a_map, other}}

  # ── Private helpers ────────────────────────────────────────────────────────

  defp validate_tags(fields) do
    case Map.fetch(fields, "tags") do
      :error ->
        {:ok, []}

      {:ok, list} when is_list(list) ->
        if Enum.all?(list, &is_binary/1) do
          {:ok, list}
        else
          {:error, {:invalid_field_type, "tags", :not_all_strings}}
        end

      {:ok, other} ->
        {:error, {:invalid_field_type, "tags", other}}
    end
  end
end
