defmodule CodePuppyControl.Support.StdioTestHelper do
  @moduledoc """
  Test helper functions for stdio-based transport testing.

  Provides `capture_stdio/2` which runs the stdio service with given inputs
  and captures the output for testing.
  """

  @doc """
  Capture stdio output during service execution.

  Takes a list of JSON-RPC request strings, runs the stdio service,
  and returns the first non-empty line of output.

  ## Examples

      request = %{"jsonrpc" => "2.0", "id" => 1, "method" => "ping", "params" => %{}}
      output = capture_stdio([Jason.encode!(request)])
      response = Jason.decode!(output)
      assert response["result"]["pong"] == true

  """
  def capture_stdio(inputs, _fun \\ nil) do
    do_capture_stdio(inputs)
  end

  defp do_capture_stdio(inputs) do
    # Write inputs to a temp file
    input_file =
      Path.join(System.tmp_dir!(), "stdio_input_#{:erlang.unique_integer([:positive])}.jsonl")

    File.write!(input_file, Enum.join(inputs, "\n") <> "\n")

    # Find the project root (where mix.exs lives)
    # __DIR__ is test/support/
    # We need to go up to elixir/code_puppy_control/
    project_path = Path.expand(Path.join(__DIR__, "../.."))

    # Verify mix.exs exists
    result =
      if File.exists?(Path.join(project_path, "mix.exs")) do
        # Use shell command with explicit cd to the project directory
        {output, exit_code} =
          System.cmd(
            "sh",
            [
              "-c",
              "cd #{project_path} && cat #{input_file} | mix code_puppy.stdio_service"
            ],
            stderr_to_stdout: true
          )

        if exit_code == 0 do
          # Find first JSON line (skip non-JSON logs like "Compiling...")
          output
          |> String.split("\n")
          |> Enum.find(&(String.starts_with?(&1, "{") and &1 != ""))
          |> case do
            nil -> "{}"
            line -> line
          end
        else
          # Return error structure for non-zero exit
          Jason.encode!(%{
            "jsonrpc" => "2.0",
            "id" => nil,
            "error" => %{
              "code" => -32000,
              "message" => "Service exited with code #{exit_code}: #{output}"
            }
          })
        end
      else
        Jason.encode!(%{
          "jsonrpc" => "2.0",
          "id" => nil,
          "error" => %{
            "code" => -32000,
            "message" => "Could not find mix.exs in #{project_path}"
          }
        })
      end

    # Clean up
    File.rm(input_file)

    result
  end
end
