defmodule Mana.ErrorClassifier do
  @moduledoc """
  Classifies exceptions into user-friendly messages with severity levels.

  Provides intelligent error classification that maps various exception types
  to appropriate severity levels, user-friendly messages, and retry guidance.
  Used by plugins and the agent system to provide consistent error handling.

  ## Severity Levels

  - `:info` - Informational, no action needed
  - `:warning` - Something went wrong but recovery is possible
  - `:error` - Operation failed, user attention needed
  - `:critical` - System-level issue, immediate attention required

  ## Usage

      try do
        File.read!("nonexistent.txt")
      rescue
        error ->
          classification = Mana.ErrorClassifier.classify(error)
          IO.puts(Mana.ErrorClassifier.format_for_user(classification))
      end
  """

  @typedoc "Severity levels for error classification"
  @type severity :: :info | :warning | :error | :critical

  @typedoc "Error classification result"
  @type classification :: %{
          message: String.t(),
          severity: severity(),
          retryable: boolean()
        }

  # Atom error lookup table
  @atom_errors %{
    :enoent => %{message: "File not found", severity: :warning, retryable: false},
    :eacces => %{message: "Permission denied", severity: :error, retryable: false},
    :eisdir => %{message: "Is a directory (expected file)", severity: :warning, retryable: false},
    :enotdir => %{message: "Not a directory", severity: :warning, retryable: false},
    :eexist => %{message: "File already exists", severity: :warning, retryable: false},
    :enospc => %{message: "No space left on device", severity: :error, retryable: false},
    :enomem => %{message: "Out of memory", severity: :error, retryable: false},
    :einval => %{message: "Invalid argument", severity: :error, retryable: false},
    :timeout => %{message: "Operation timed out", severity: :warning, retryable: true}
  }

  @doc """
  Classify an exception or error term.

  Takes an exception struct, error tuple, or any error term and returns
  a classification map with user-friendly message, severity level, and
  retryability information.

  ## Parameters

  - `error` - An exception struct, error tuple, or error term

  ## Returns

  - `classification` - Map with `:message`, `:severity`, and `:retryable` keys

  ## Examples

      iex> Mana.ErrorClassifier.classify(%File.Error{reason: :enoent, path: "/tmp/missing.txt"})
      %{message: "File not found: /tmp/missing.txt", severity: :warning, retryable: false}

      iex> Mana.ErrorClassifier.classify({:timeout, :gen_server})
      %{message: "Operation timed out", severity: :warning, retryable: true}
  """
  @spec classify(Exception.t() | term()) :: classification()

  # File operation errors - delegated to helper
  def classify(%File.Error{} = error), do: classify_file_error(error)

  # JSON parsing errors - delegated to helper
  def classify(%Jason.DecodeError{} = error), do: classify_json_error(error)

  # Pattern match failures and standard errors - delegated to helper
  def classify(%MatchError{} = error), do: classify_standard_error(error)
  def classify(%RuntimeError{} = error), do: classify_standard_error(error)
  def classify(%ArgumentError{} = error), do: classify_standard_error(error)
  def classify(%FunctionClauseError{} = error), do: classify_standard_error(error)
  def classify(%KeyError{} = error), do: classify_standard_error(error)
  def classify(%CaseClauseError{} = error), do: classify_standard_error(error)
  def classify(%Protocol.UndefinedError{} = error), do: classify_standard_error(error)

  # Timeout errors - delegated to helper
  def classify({:timeout, _server} = error), do: classify_timeout(error)
  def classify(:timeout = error), do: classify_timeout(error)

  # Generic exception types - delegated to helper
  def classify(%{__struct__: struct_name} = error) when is_atom(struct_name) do
    classify_generic_exception(error)
  end

  # Atom errors - delegated to helper
  def classify(error) when is_atom(error) do
    classify_atom_error(error)
  end

  # Tuple errors - delegated to helper
  def classify({:error, _reason} = error), do: classify_tuple_error(error)

  # Catch-all for unknown error types
  def classify(error) do
    %{
      message: "Unexpected error: #{inspect(error, limit: 200)}",
      severity: :error,
      retryable: false
    }
  end

  # Private helper functions

  defp classify_file_error(%{reason: :enoent, path: path}) do
    %{message: "File not found: #{path}", severity: :warning, retryable: false}
  end

  defp classify_file_error(%{reason: :eacces, path: path}) do
    %{message: "Permission denied: #{path}", severity: :error, retryable: false}
  end

  defp classify_file_error(%{reason: :eisdir, path: path}) do
    %{message: "Expected a file but found a directory: #{path}", severity: :warning, retryable: false}
  end

  defp classify_file_error(%{reason: :enotdir, path: path}) do
    %{message: "Not a valid directory path: #{path}", severity: :warning, retryable: false}
  end

  defp classify_file_error(%{reason: :eexist, path: path}) do
    %{message: "File already exists: #{path}", severity: :warning, retryable: false}
  end

  defp classify_file_error(%{reason: reason, path: path}) do
    %{message: "File error (#{reason}) on: #{path}", severity: :error, retryable: false}
  end

  defp classify_json_error(%{data: data, position: position}) do
    preview = String.slice(data, 0, 100)
    message = if position, do: "Invalid JSON at position #{position}", else: "Invalid JSON"
    %{message: "#{message}: #{preview}", severity: :error, retryable: false}
  end

  defp classify_json_error(%{data: data}) do
    preview = String.slice(data, 0, 100)
    %{message: "Invalid JSON: #{preview}", severity: :error, retryable: false}
  end

  defp classify_standard_error(%MatchError{term: term}) do
    %{message: "Pattern match failed: #{inspect(term, limit: 100)}", severity: :error, retryable: false}
  end

  defp classify_standard_error(%RuntimeError{message: msg}) do
    %{message: msg, severity: :error, retryable: true}
  end

  defp classify_standard_error(%ArgumentError{message: msg}) do
    %{message: "Invalid argument: #{msg}", severity: :error, retryable: false}
  end

  defp classify_standard_error(%FunctionClauseError{module: module, function: function, arity: arity}) do
    %{
      message: "No matching function clause for #{module}.#{function}/#{arity}",
      severity: :error,
      retryable: false
    }
  end

  defp classify_standard_error(%KeyError{key: key, term: term}) do
    %{
      message: "Key #{inspect(key)} not found in #{inspect(term, limit: 50)}",
      severity: :error,
      retryable: false
    }
  end

  defp classify_standard_error(%CaseClauseError{term: term}) do
    %{message: "No case clause matching: #{inspect(term, limit: 100)}", severity: :error, retryable: false}
  end

  defp classify_standard_error(%Protocol.UndefinedError{protocol: protocol, value: value}) do
    %{
      message: "Protocol #{protocol} not implemented for #{inspect(value, limit: 50)}",
      severity: :error,
      retryable: false
    }
  end

  defp classify_timeout({:timeout, _server}) do
    %{message: "Operation timed out waiting for response", severity: :warning, retryable: true}
  end

  defp classify_timeout(:timeout) do
    %{message: "Operation timed out", severity: :warning, retryable: true}
  end

  defp classify_generic_exception(error) do
    if Map.get(error, :__exception__) do
      message = Exception.message(error) || inspect(error, limit: 100)
      %{message: message, severity: :error, retryable: false}
    else
      %{message: "Unexpected error: #{inspect(error, limit: 200)}", severity: :error, retryable: false}
    end
  end

  defp classify_atom_error(error) do
    Map.get(@atom_errors, error, %{message: "Error: #{error}", severity: :error, retryable: false})
  end

  defp classify_tuple_error({:error, reason}) when is_atom(reason) do
    classify(reason)
  end

  defp classify_tuple_error({:error, reason}) do
    %{message: "Error: #{inspect(reason, limit: 100)}", severity: :error, retryable: false}
  end

  @doc """
  Format a classification for user display.

  Takes a classification map and returns a formatted string with
  appropriate emoji/icon prefix based on severity.

  ## Parameters

  - `classification` - The classification map from `classify/1`

  ## Returns

  - `String.t()` - Formatted user-friendly message

  ## Examples

      iex> classification = %{message: "File not found", severity: :warning, retryable: false}
      iex> Mana.ErrorClassifier.format_for_user(classification)
      "⚠️ File not found"
  """
  @spec format_for_user(classification()) :: String.t()
  def format_for_user(%{message: message, severity: severity}) do
    icon =
      case severity do
        :info -> "ℹ️"
        :warning -> "⚠️"
        :error -> "❌"
        :critical -> "🚨"
      end

    "#{icon} #{message}"
  end

  @doc """
  Format a classification with retry guidance.

  Similar to `format_for_user/1` but includes retry guidance for
  retryable errors.

  ## Parameters

  - `classification` - The classification map from `classify/1`

  ## Returns

  - `String.t()` - Formatted message with retry guidance
  """
  @spec format_with_retry(classification()) :: String.t()
  def format_with_retry(%{message: message, severity: severity, retryable: true}) do
    base = format_for_user(%{message: message, severity: severity})
    "#{base} (This error may resolve if you retry)"
  end

  def format_with_retry(classification) do
    format_for_user(classification)
  end
end
