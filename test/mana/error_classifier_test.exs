defmodule Mana.ErrorClassifierTest do
  use ExUnit.Case

  alias Mana.ErrorClassifier

  describe "classify/1 with File.Error" do
    test "classifies enoent (file not found)" do
      error = %File.Error{reason: :enoent, path: "/tmp/missing.txt"}
      result = ErrorClassifier.classify(error)

      assert result.message == "File not found: /tmp/missing.txt"
      assert result.severity == :warning
      assert result.retryable == false
    end

    test "classifies eacces (permission denied)" do
      error = %File.Error{reason: :eacces, path: "/etc/shadow"}
      result = ErrorClassifier.classify(error)

      assert result.message == "Permission denied: /etc/shadow"
      assert result.severity == :error
      assert result.retryable == false
    end

    test "classifies eisdir (is a directory)" do
      error = %File.Error{reason: :eisdir, path: "/tmp"}
      result = ErrorClassifier.classify(error)

      assert result.message == "Expected a file but found a directory: /tmp"
      assert result.severity == :warning
      assert result.retryable == false
    end

    test "classifies enotdir (not a directory)" do
      error = %File.Error{reason: :enotdir, path: "/tmp/file.txt/subdir"}
      result = ErrorClassifier.classify(error)

      assert result.message == "Not a valid directory path: /tmp/file.txt/subdir"
      assert result.severity == :warning
      assert result.retryable == false
    end

    test "classifies eexist (file exists)" do
      error = %File.Error{reason: :eexist, path: "/tmp/exists.txt"}
      result = ErrorClassifier.classify(error)

      assert result.message == "File already exists: /tmp/exists.txt"
      assert result.severity == :warning
      assert result.retryable == false
    end

    test "classifies unknown file error" do
      error = %File.Error{reason: :unknown, path: "/tmp/test.txt"}
      result = ErrorClassifier.classify(error)

      assert result.message == "File error (unknown) on: /tmp/test.txt"
      assert result.severity == :error
      assert result.retryable == false
    end
  end

  describe "classify/1 with Jason.DecodeError" do
    test "classifies JSON decode errors" do
      error = %Jason.DecodeError{data: "invalid json {", position: 10}
      result = ErrorClassifier.classify(error)

      assert result.message =~ "Invalid JSON"
      assert result.message =~ "invalid json"
      assert result.severity == :error
      assert result.retryable == false
    end

    test "classifies JSON decode errors without position" do
      error = %Jason.DecodeError{data: "bad json"}
      result = ErrorClassifier.classify(error)

      assert result.message == "Invalid JSON: bad json"
      assert result.severity == :error
    end
  end

  describe "classify/1 with MatchError" do
    test "classifies match errors" do
      error = %MatchError{term: {:unexpected, :value}}
      result = ErrorClassifier.classify(error)

      assert result.message =~ "Pattern match failed"
      assert result.message =~ "{:unexpected, :value}"
      assert result.severity == :error
      assert result.retryable == false
    end
  end

  describe "classify/1 with RuntimeError" do
    test "classifies runtime errors" do
      error = %RuntimeError{message: "Something went wrong"}
      result = ErrorClassifier.classify(error)

      assert result.message == "Something went wrong"
      assert result.severity == :error
      assert result.retryable == true
    end
  end

  describe "classify/1 with ArgumentError" do
    test "classifies argument errors" do
      error = %ArgumentError{message: "expected list, got: nil"}
      result = ErrorClassifier.classify(error)

      assert result.message == "Invalid argument: expected list, got: nil"
      assert result.severity == :error
      assert result.retryable == false
    end
  end

  describe "classify/1 with FunctionClauseError" do
    test "classifies function clause errors" do
      error = %FunctionClauseError{module: MyModule, function: :my_func, arity: 2}
      result = ErrorClassifier.classify(error)

      assert result.message =~ "No matching function clause"
      assert result.message =~ "MyModule.my_func/2"
      assert result.severity == :error
      assert result.retryable == false
    end
  end

  describe "classify/1 with KeyError" do
    test "classifies key errors" do
      error = %KeyError{key: :missing_key, term: %{existing: "value"}}
      result = ErrorClassifier.classify(error)

      assert result.message =~ "Key :missing_key not found"
      assert result.severity == :error
      assert result.retryable == false
    end
  end

  describe "classify/1 with CaseClauseError" do
    test "classifies case clause errors" do
      error = %CaseClauseError{term: :unexpected_value}
      result = ErrorClassifier.classify(error)

      assert result.message =~ "No case clause matching"
      assert result.message =~ ":unexpected_value"
      assert result.severity == :error
    end
  end

  describe "classify/1 with Protocol.UndefinedError" do
    test "classifies protocol errors" do
      error = %Protocol.UndefinedError{protocol: Enumerable, value: nil}
      result = ErrorClassifier.classify(error)

      assert result.message =~ "Protocol Elixir.Enumerable not implemented"
      assert result.severity == :error
    end
  end

  describe "classify/1 with timeout errors" do
    test "classifies timeout tuple" do
      result = ErrorClassifier.classify({:timeout, :gen_server})

      assert result.message == "Operation timed out waiting for response"
      assert result.severity == :warning
      assert result.retryable == true
    end

    test "classifies timeout atom" do
      result = ErrorClassifier.classify(:timeout)

      assert result.message == "Operation timed out"
      assert result.severity == :warning
      assert result.retryable == true
    end
  end

  describe "classify/1 with atom errors" do
    test "classifies enoent atom" do
      result = ErrorClassifier.classify(:enoent)

      assert result.message == "File not found"
      assert result.severity == :warning
      assert result.retryable == false
    end

    test "classifies eacces atom" do
      result = ErrorClassifier.classify(:eacces)

      assert result.message == "Permission denied"
      assert result.severity == :error
      assert result.retryable == false
    end

    test "classifies timeout atom as retryable" do
      result = ErrorClassifier.classify(:timeout)

      assert result.message == "Operation timed out"
      assert result.severity == :warning
      assert result.retryable == true
    end

    test "classifies unknown atoms" do
      result = ErrorClassifier.classify(:unknown_error)

      assert result.message == "Error: unknown_error"
      assert result.severity == :error
    end
  end

  describe "classify/1 with tuple errors" do
    test "classifies {:error, atom} tuples" do
      result = ErrorClassifier.classify({:error, :enoent})

      assert result.message == "File not found"
      assert result.severity == :warning
    end

    test "classifies {:error, term} tuples" do
      result = ErrorClassifier.classify({:error, "custom error message"})

      assert result.message == "Error: \"custom error message\""
      assert result.severity == :error
    end
  end

  describe "classify/1 with generic exceptions" do
    test "classifies unknown exception types" do
      # Use a real exception type but with an unusual message
      error = %RuntimeError{message: "some runtime issue"}
      result = ErrorClassifier.classify(error)

      assert result.message == "some runtime issue"
      assert result.severity == :error
      assert result.retryable == true
    end

    test "classifies plain maps as unexpected errors" do
      result = ErrorClassifier.classify(%{some: "data"})

      assert result.message =~ "Unexpected error"
      assert result.severity == :error
      assert result.retryable == false
    end

    test "classifies arbitrary terms" do
      result = ErrorClassifier.classify("random string")

      assert result.message =~ "Unexpected error"
      assert result.message =~ "random string"
    end
  end

  describe "format_for_user/1" do
    test "formats info severity" do
      classification = %{message: "Information", severity: :info}
      assert ErrorClassifier.format_for_user(classification) == "ℹ️ Information"
    end

    test "formats warning severity" do
      classification = %{message: "Warning message", severity: :warning}
      assert ErrorClassifier.format_for_user(classification) == "⚠️ Warning message"
    end

    test "formats error severity" do
      classification = %{message: "Error occurred", severity: :error}
      assert ErrorClassifier.format_for_user(classification) == "❌ Error occurred"
    end

    test "formats critical severity" do
      classification = %{message: "Critical failure", severity: :critical}
      assert ErrorClassifier.format_for_user(classification) == "🚨 Critical failure"
    end
  end

  describe "format_with_retry/1" do
    test "includes retry guidance for retryable errors" do
      classification = %{message: "Timeout", severity: :warning, retryable: true}
      result = ErrorClassifier.format_with_retry(classification)

      assert result =~ "Timeout"
      assert result =~ "may resolve if you retry"
    end

    test "excludes retry guidance for non-retryable errors" do
      classification = %{message: "File not found", severity: :warning, retryable: false}
      result = ErrorClassifier.format_with_retry(classification)

      assert result == "⚠️ File not found"
      refute result =~ "retry"
    end
  end
end
