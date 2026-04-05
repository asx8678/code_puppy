defmodule Mana.Shell.ResultTest do
  use ExUnit.Case

  alias Mana.Shell.Result

  describe "struct definition" do
    test "has all required fields" do
      result = %Result{
        success: true,
        command: "echo hello",
        stdout: "hello",
        stderr: "",
        exit_code: 0,
        execution_time: 100,
        timeout?: false,
        user_interrupted?: false
      }

      assert result.success == true
      assert result.command == "echo hello"
      assert result.stdout == "hello"
      assert result.stderr == ""
      assert result.exit_code == 0
      assert result.execution_time == 100
      assert result.timeout? == false
      assert result.user_interrupted? == false
    end

    test "supports success false for failed commands" do
      result = %Result{
        success: false,
        command: "exit 1",
        stdout: "",
        stderr: "error",
        exit_code: 1,
        execution_time: 50,
        timeout?: false,
        user_interrupted?: false
      }

      assert result.success == false
      assert result.exit_code == 1
    end

    test "supports timeout indication" do
      result = %Result{
        success: false,
        command: "sleep 100",
        stdout: "",
        stderr: "timeout",
        exit_code: -1,
        execution_time: 30_000,
        timeout?: true,
        user_interrupted?: false
      }

      assert result.timeout? == true
      assert result.exit_code == -1
    end

    test "supports user interrupted indication" do
      result = %Result{
        success: false,
        command: "sleep 100",
        stdout: "",
        stderr: "killed",
        exit_code: -1,
        execution_time: 5000,
        timeout?: false,
        user_interrupted?: true
      }

      assert result.user_interrupted? == true
    end
  end

  describe "type specification" do
    test "struct can be created with all field types" do
      result = %Result{
        success: true,
        command: "test",
        stdout: "output",
        stderr: "error",
        exit_code: 0,
        execution_time: 42,
        timeout?: false,
        user_interrupted?: false
      }

      assert is_boolean(result.success)
      assert is_binary(result.command)
      assert is_binary(result.stdout)
      assert is_binary(result.stderr)
      assert is_integer(result.exit_code)
      assert is_integer(result.execution_time)
      assert is_boolean(result.timeout?)
      assert is_boolean(result.user_interrupted?)
    end
  end
end
