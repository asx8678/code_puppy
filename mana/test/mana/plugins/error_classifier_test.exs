defmodule Mana.Plugins.ErrorClassifierTest do
  use ExUnit.Case

  alias Mana.Plugins.ErrorClassifier

  describe "behaviour compliance" do
    test "implements Mana.Plugin.Behaviour" do
      behaviours = ErrorClassifier.__info__(:attributes)[:behaviour] || []
      assert Mana.Plugin.Behaviour in behaviours
    end

    test "has required callbacks" do
      assert function_exported?(ErrorClassifier, :name, 0)
      assert function_exported?(ErrorClassifier, :init, 1)
      assert function_exported?(ErrorClassifier, :hooks, 0)
      assert function_exported?(ErrorClassifier, :terminate, 0)
    end
  end

  describe "name/0" do
    test "returns correct plugin name" do
      assert ErrorClassifier.name() == "error_classifier"
    end
  end

  describe "init/1" do
    test "initializes with default config" do
      assert {:ok, state} = ErrorClassifier.init(%{})
      assert state.config == %{}
    end

    test "initializes with custom config" do
      assert {:ok, state} = ErrorClassifier.init(%{log_level: :debug})
      assert state.config.log_level == :debug
    end
  end

  describe "hooks/0" do
    test "returns expected hooks" do
      hooks = ErrorClassifier.hooks()
      hook_names = Enum.map(hooks, fn {name, _func} -> name end)
      assert :agent_exception in hook_names
      assert :agent_run_end in hook_names
    end
  end

  describe "classify/1" do
    test "classifies rate limit errors from strings" do
      result = ErrorClassifier.classify("rate limit exceeded")
      assert result.category == :rate_limit
      assert result.retryable == true
    end

    test "classifies 429 errors" do
      result = ErrorClassifier.classify("HTTP 429 Too Many Requests")
      assert result.category == :rate_limit
      assert result.retryable == true
    end

    test "classifies auth errors" do
      result = ErrorClassifier.classify("Unauthorized access")
      assert result.category == :auth
      assert result.retryable == false
    end

    test "classifies 403 forbidden" do
      result = ErrorClassifier.classify("403 Forbidden")
      assert result.category == :auth
    end

    test "classifies timeout errors" do
      result = ErrorClassifier.classify("Request timeout after 30s")
      assert result.category == :timeout
      assert result.retryable == true
    end

    test "classifies model errors" do
      result = ErrorClassifier.classify("Model not found: gpt-5")
      assert result.category == :model_error
    end

    test "classifies context length errors" do
      result = ErrorClassifier.classify("context length exceeded maximum")
      assert result.category == :model_error
    end

    test "classifies tool errors" do
      result = ErrorClassifier.classify("Tool execution failed: file not accessible")
      assert result.category == :tool_error
    end

    test "classifies unknown errors" do
      result = ErrorClassifier.classify("Something weird happened")
      assert result.category == :unknown
    end

    test "classifies error tuples" do
      result = ErrorClassifier.classify({:error, :timeout})
      assert result.category == :timeout
    end

    test "classifies atoms" do
      result = ErrorClassifier.classify(:timeout)
      assert result.category == :timeout

      result = ErrorClassifier.classify(:unauthorized)
      assert result.category == :auth

      result = ErrorClassifier.classify(:something_else)
      assert result.category == :unknown
    end

    test "classifies RuntimeError" do
      result = ErrorClassifier.classify(%RuntimeError{message: "timeout exceeded"})
      assert result.category == :timeout
    end

    test "classifies exception with message" do
      result = ErrorClassifier.classify(%RuntimeError{message: "Rate limit hit"})
      assert result.category == :rate_limit
    end
  end

  describe "on_agent_exception/3" do
    test "handles exception and returns :ok" do
      assert :ok == ErrorClassifier.on_agent_exception(%RuntimeError{message: "test"}, [], [])
    end

    test "handles nil exception gracefully" do
      assert :ok == ErrorClassifier.on_agent_exception(nil, [], [])
    end
  end

  describe "on_agent_run_end/7" do
    test "returns :ok for successful runs" do
      assert :ok ==
               ErrorClassifier.on_agent_run_end("agent", "model", "session", true, nil, nil, nil)
    end

    test "classifies errors from failed runs" do
      assert :ok ==
               ErrorClassifier.on_agent_run_end(
                 "agent",
                 "model",
                 "session",
                 false,
                 "timeout occurred",
                 nil,
                 nil
               )
    end

    test "handles nil error on failed run" do
      assert :ok ==
               ErrorClassifier.on_agent_run_end("agent", "model", nil, false, nil, nil, nil)
    end
  end

  describe "terminate/0" do
    test "returns :ok" do
      assert ErrorClassifier.terminate() == :ok
    end
  end
end
