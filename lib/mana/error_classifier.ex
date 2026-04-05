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

  # File operation errors
  def classify(%File.Error{reason: :enoent, path: path}) do
    %{
      message: "File not found: #{path}",
      severity: :warning,
      retryable: false
    }
  end

  def classify(%File.Error{reason: :eacces, path: path}) do
    %{
      message: "Permission denied: #{path}",
      severity: :error,
      retryable: false
    }
  end

  def classify(%File.Error{reason: :eisdir, path: path}) do
    %{
      message: "Expected a file but found a directory: #{path}",
      severity: :warning,
      retryable: false
    }
  end

  def classify(%File.Error{reason: :enotdir, path: path}) do
    %{
      message: "Not a valid directory path: #{path}",
      severity: :warning,
      retryable: false
    }
  end

  def classify(%File.Error{reason: :eexist, path: path}) do
    %{
      message: "File already exists: #{path}",
      severity: :warning,
      retryable: false
    }
  end

  def classify(%File.Error{reason: reason, path: path}) do
    %{
      message: "File error (#{reason}) on: #{path}",
      severity: :error,
      retryable: false
    }
  end

  # JSON parsing errors
  def classify(%Jason.DecodeError{data: data, position: position}) do
    preview = String.slice(data, 0, 100)
    message = if position, do: "Invalid JSON at position #{position}", else: "Invalid JSON"

    %{
      message: "#{message}: #{preview}",
      severity: :error,
      retryable: false
    }
  end

  def classify(%Jason.DecodeError{data: data}) do
    preview = String.slice(data, 0, 100)

    %{
      message: "Invalid JSON: #{preview}",
      severity: :error,
      retryable: false
    }
  end

  # Pattern match failures
  def classify(%MatchError{term: term}) do
    %{
      message: "Pattern match failed: #{inspect(term, limit: 100)}",
      severity: :error,
      retryable: false
    }
  end

  # Runtime errors
  def classify(%RuntimeError{message: msg}) do
    %{
      message: msg,
      severity: :error,
      retryable: true
    }
  end

  # Argument errors
  def classify(%ArgumentError{message: msg}) do
    %{
      message: "Invalid argument: #{msg}",
      severity: :error,
      retryable: false
    }
  end

  # Function clause errors
  def classify(%FunctionClauseError{module: module, function: function, arity: arity}) do
    %{
      message: "No matching function clause for #{module}.#{function}/#{arity}",
      severity: :error,
      retryable: false
    }
  end

  # Key errors (missing map keys)
  def classify(%KeyError{key: key, term: term}) do
    %{
      message: "Key #{inspect(key)} not found in #{inspect(term, limit: 50)}",
      severity: :error,
      retryable: false
    }
  end

  # Case clause errors
  def classify(%CaseClauseError{term: term}) do
    %{
      message: "No case clause matching: #{inspect(term, limit: 100)}",
      severity: :error,
      retryable: false
    }
  end

  # Protocol errors
  def classify(%Protocol.UndefinedError{protocol: protocol, value: value}) do
    %{
      message: "Protocol #{protocol} not implemented for #{inspect(value, limit: 50)}",
      severity: :error,
      retryable: false
    }
  end

  # Timeout errors
  def classify({:timeout, _server}) do
    %{
      message: "Operation timed out waiting for response",
      severity: :warning,
      retryable: true
    }
  end

  def classify(:timeout) do
    %{
      message: "Operation timed out",
      severity: :warning,
      retryable: true
    }
  end

  # Generic exception types - must come before the catch-all atom clause
  def classify(%{__struct__: struct_name} = error) when is_atom(struct_name) do
    # Check if it's a proper exception with __exception__ marker
    if Map.get(error, :__exception__) do
      message = if Exception.message(error), do: Exception.message(error), else: inspect(error, limit: 100)

      %{
        message: message,
        severity: :error,
        retryable: false
      }
    else
      # Not a real exception, treat as unexpected error
      %{
        message: "Unexpected error: #{inspect(error, limit: 200)}",
        severity: :error,
        retryable: false
      }
    end
  end

  # Atom errors - common Erlang/Elixir error atoms
  def classify(error) when is_atom(error) do
    case error do
      :enoent -> %{message: "File not found", severity: :warning, retryable: false}
      :eacces -> %{message: "Permission denied", severity: :error, retryable: false}
      :eisdir -> %{message: "Is a directory (expected file)", severity: :warning, retryable: false}
      :enotdir -> %{message: "Not a directory", severity: :warning, retryable: false}
      :eexist -> %{message: "File already exists", severity: :warning, retryable: false}
      :enospc -> %{message: "No space left on device", severity: :error, retryable: false}
      :enomem -> %{message: "Out of memory", severity: :error, retryable: false}
      :einval -> %{message: "Invalid argument", severity: :error, retryable: false}
      :timeout -> %{message: "Operation timed out", severity: :warning, retryable: true}
      _ -> %{message: "Error: #{error}", severity: :error, retryable: false}
    end
  end

  # Tuple errors (common in Erlang/Elixir)
  def classify({:error, reason}) when is_atom(reason) do
    classify(reason)
  end

  def classify({:error, reason}) do
    %{
      message: "Error: #{inspect(reason, limit: 100)}",
      severity: :error,
      retryable: false
    }
  end

  # Catch-all for unknown error types
  def classify(error) do
    %{
      message: "Unexpected error: #{inspect(error, limit: 200)}",
      severity: :error,
      retryable: false
    }
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
