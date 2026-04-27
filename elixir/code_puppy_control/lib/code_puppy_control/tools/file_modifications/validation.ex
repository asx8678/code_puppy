defmodule CodePuppyControl.Tools.FileModifications.Validation do
  @moduledoc """
  Post-edit syntax validation for file modifications.

  Port of `code_puppy/tools/file_modifications.py:_maybe_attach_syntax_warning`.

  Validates file syntax after a successful edit operation and attaches
  advisory warnings to the result. The edit is NEVER blocked by validation
  failures — this is purely advisory for the agent to self-correct.

  ## Design

  - Validation is opt-in via configuration
  - Fail-open: validation errors are logged but never block writes
  - Timeout-bounded: each validation runs with a time limit
  - Extension-based: only validates files with parseable extensions
  """

  require Logger

  @validation_timeout_ms 500

  # File extensions that support syntax validation
  @validatable_extensions ~w(.ex .exs .erl .hrl .py .js .ts .tsx .rs .json .yaml .yml .toml)

  @doc """
  Attach a syntax warning to the result if validation detects issues.

  This function mutates the result map in-place by adding a `:syntax_warning`
  key if post-edit validation finds syntax errors. The edit operation itself
  is NOT blocked — this is purely advisory.

  ## Returns

  The result map, potentially with a `:syntax_warning` key added.

  ## Examples

      iex> Validation.maybe_attach_warning(%{success: true, path: "/tmp/test.ex"}, "/tmp/test.ex")
      %{success: true, path: "/tmp/test.ex"}
  """
  @spec maybe_attach_warning(map(), Path.t()) :: map()
  def maybe_attach_warning(result, file_path) do
    # Only validate successful operations
    unless result[:success] == true do
      result
    else
      do_maybe_attach(result, file_path)
    end
  end

  @doc """
  Check if a file extension is validatable.

  ## Examples

      iex> Validation.validatable_extension?("/tmp/file.ex")
      true

      iex> Validation.validatable_extension?("/tmp/file.txt")
      false
  """
  @spec validatable_extension?(Path.t()) :: boolean()
  def validatable_extension?(file_path) do
    ext = Path.extname(file_path) |> String.downcase()
    ext in @validatable_extensions
  end

  @doc """
  Check if post-edit validation is enabled.

  Reads from application config. Default: `true`.
  """
  @spec validation_enabled?() :: boolean()
  def validation_enabled? do
    Application.get_env(:code_puppy_control, :post_edit_validation, true)
  end

  @doc """
  Validate file content for syntax errors.

  Returns `{:ok, :valid}` or `{:warning, message}`.
  Always returns `{:ok, :valid}` if validation is disabled or the
  extension is not validatable (fail-open guarantee).

  ## Examples

      iex> Validation.validate_file("/tmp/test.ex", "def foo, do: :bar")
      {:ok, :valid}  # or {:warning, "message"} if syntax errors found
  """
  @spec validate_file(Path.t(), String.t()) :: {:ok, :valid} | {:warning, String.t()}
  def validate_file(file_path, content) do
    if not validation_enabled?() or not validatable_extension?(file_path) do
      {:ok, :valid}
    else
      do_validate(file_path, content)
    end
  end

  # ── Private ────────────────────────────────────────────────────────────

  defp do_maybe_attach(result, file_path) do
    case File.read(file_path) do
      {:ok, content} ->
        case validate_file(file_path, content) do
          {:ok, :valid} ->
            result

          {:warning, message} ->
            Map.put(result, :syntax_warning, message)
        end

      {:error, _} ->
        # Can't read file — fail-open
        result
    end
  rescue
    e ->
      # Never let validation failures break the edit operation
      Logger.debug("post-edit validation skipped for #{file_path}: #{inspect(e)}")
      result
  end

  # Extension-specific validation
  defp do_validate(file_path, content) do
    ext = Path.extname(file_path) |> String.downcase()

    # Try to use TaskSupervisor if available, otherwise run inline
    case Process.whereis(CodePuppyControl.TaskSupervisor) do
      nil ->
        # TaskSupervisor not available — validate inline (fail-open on crash)
        try do
          validate_extension(ext, content)
        rescue
          _ -> {:ok, :valid}
        end

      _pid ->
        validate_with_timeout(ext, content)
    end
  end

  defp validate_with_timeout(ext, content) do
    task =
      Task.Supervisor.async_nolink(
        CodePuppyControl.TaskSupervisor,
        fn -> validate_extension(ext, content) end
      )

    case Task.yield(task, @validation_timeout_ms) || Task.shutdown(task, 100) do
      {:ok, {:ok, :valid}} -> {:ok, :valid}
      {:ok, {:warning, msg}} -> {:warning, msg}
      {:exit, _reason} -> {:ok, :valid}
      nil -> {:ok, :valid}
    end
  end

  # Elixir validation
  defp validate_extension(ext, content) when ext in ~w(.ex .exs) do
    case Code.string_to_quoted(content, file: "validation_check") do
      {:ok, _} -> {:ok, :valid}
      {:error, {meta, error_msg, token}} ->
        line = Keyword.get(meta, :line, 0)
        {:warning, "Syntax error on line #{line}: #{error_msg} #{token}"}
    end
  end

  # Erlang validation (basic)
  defp validate_extension(ext, content) when ext in ~w(.erl .hrl) do
    # Basic check: try to scan tokens
    try do
      :erl_scan.string(String.to_charlist(content))
      {:ok, :valid}
    rescue
      _ -> {:warning, "Erlang tokenization failed — possible syntax error"}
    end
  end

  # JSON validation
  defp validate_extension(".json", content) do
    case Jason.decode(content) do
      {:ok, _} -> {:ok, :valid}
      {:error, %Jason.DecodeError{} = e} -> {:warning, "Invalid JSON: #{Exception.message(e)}"}
    end
  end

  # TOML validation (basic)
  defp validate_extension(".toml", _content) do
    # No built-in TOML parser — skip validation
    {:ok, :valid}
  end

  # YAML validation (basic)
  defp validate_extension(ext, _content) when ext in ~w(.yaml .yml) do
    # No built-in YAML parser — skip validation
    {:ok, :valid}
  end

  # Python/JS/TS/Rust — defer to external parsers via bridge
  defp validate_extension(_ext, _content) do
    # Could integrate with elixir_bridge for external parsing
    # For now, fail-open (no validation available)
    {:ok, :valid}
  end
end
