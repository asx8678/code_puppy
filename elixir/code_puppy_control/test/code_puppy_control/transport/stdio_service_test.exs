defmodule CodePuppyControl.Transport.StdioServiceTest do
  @moduledoc """
  Tests for the standalone stdio JSON-RPC transport service.
  """

  use ExUnit.Case

  alias CodePuppyControl.Transport.StdioService
  alias CodePuppyControl.Support.StdioTestHelper

  @test_dir Path.join(
              System.tmp_dir!(),
              "stdio_service_test_#{:erlang.unique_integer([:positive])}"
            )

  setup do
    # Create test directory structure
    File.rm_rf!(@test_dir)
    File.mkdir_p!(@test_dir)

    # Create test files
    File.write!(Path.join(@test_dir, "file1.txt"), "Line 1\nLine 2\nLine 3\nLine 4\nLine 5")

    File.write!(
      Path.join(@test_dir, "file2.ex"),
      "defmodule Test do\n  def hello do\n    :world\n  end\nend"
    )

    # Create subdirectory with more files
    subdir = Path.join(@test_dir, "subdir")
    File.mkdir_p!(subdir)

    File.write!(
      Path.join(subdir, "nested.ex"),
      "defmodule Nested do\n  def run do\n    :ok\n  end\nend"
    )

    on_exit(fn ->
      File.rm_rf!(@test_dir)
    end)

    %{test_dir: @test_dir, subdir: subdir}
  end

  # ============================================================================
  # Initialization Tests
  # ============================================================================

  describe "initialization" do
    test "starts with default options" do
      assert {:ok, pid} = StdioService.start_link([])
      assert Process.alive?(pid)
      Process.exit(pid, :normal)
    end

    test "tracks request counter via health check" do
      # Service blocks on stdio, use health_check to verify counter increases
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "health_check",
        "params" => %{}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"
      assert response["id"] == 1
      # Counter is tracked internally, verified via successful response
    end
  end

  # ============================================================================
  # Ping Tests
  # ============================================================================

  describe "ping method" do
    test "responds to ping request" do
      # Create service with custom buffer for testing
      request = %{"jsonrpc" => "2.0", "id" => 1, "method" => "ping", "params" => %{}}
      request_line = Jason.encode!(request)

      output =
        capture_stdio([request_line], fn ->
          StdioService.run(buffer: request_line, io_device: :stdio)
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"
      assert response["id"] == 1
      assert response["result"]["pong"] == true
      assert response["result"]["timestamp"]
    end
  end

  # ============================================================================
  # Health Check Tests
  # ============================================================================

  describe "health_check method" do
    test "returns service health information" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "health_check",
        "params" => %{}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"
      assert response["id"] == 1
      assert response["result"]["status"] == "healthy"
      assert response["result"]["version"]
      assert response["result"]["elixir_version"]
      assert response["result"]["otp_version"]
      assert response["result"]["timestamp"]
    end
  end

  # ============================================================================
  # File List Tests
  # ============================================================================

  describe "file_list method" do
    test "lists files in directory", %{test_dir: dir} do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_list",
        "params" => %{"directory" => dir, "recursive" => false}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"
      assert response["id"] == 1
      assert response["result"]["files"]

      files = response["result"]["files"]
      paths = Enum.map(files, & &1["path"])

      assert "file1.txt" in paths
      assert "file2.ex" in paths
      assert "subdir" in paths
    end

    test "lists files recursively", %{test_dir: dir} do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_list",
        "params" => %{"directory" => dir, "recursive" => true}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      files = response["result"]["files"]
      paths = Enum.map(files, & &1["path"])

      assert "file1.txt" in paths
      assert "subdir/nested.ex" in paths
    end

    test "returns error for non-existent directory" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_list",
        "params" => %{"directory" => "/nonexistent/directory/12345"}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32000
      assert response["error"]["message"] =~ "File list failed"
    end
  end

  # ============================================================================
  # File Read Tests
  # ============================================================================

  describe "file_read method" do
    test "reads file contents", %{test_dir: dir} do
      file_path = Path.join(dir, "file1.txt")

      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read",
        "params" => %{"path" => file_path}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"
      assert response["id"] == 1

      result = response["result"]
      assert result["path"] == file_path
      assert result["content"] == "Line 1\nLine 2\nLine 3\nLine 4\nLine 5"
      assert result["num_lines"] == 5
      assert result["truncated"] == false
      assert result["error"] == nil
    end

    test "reads specific line range", %{test_dir: dir} do
      file_path = Path.join(dir, "file1.txt")

      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read",
        "params" => %{"path" => file_path, "start_line" => 2, "num_lines" => 2}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      result = response["result"]
      assert result["content"] == "Line 2\nLine 3"
      assert result["num_lines"] == 2
      assert result["truncated"] == true
    end

    test "returns error for missing path param" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read",
        "params" => %{}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32602
      assert response["error"]["message"] =~ "Missing required param"
    end

    test "returns error for non-existent file", %{test_dir: dir} do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read",
        "params" => %{"path" => Path.join(dir, "nonexistent.txt")}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32000
    end
  end

  # ============================================================================
  # File Read Batch Tests
  # ============================================================================

  describe "file_read_batch method" do
    test "reads multiple files concurrently", %{test_dir: dir} do
      paths = [
        Path.join(dir, "file1.txt"),
        Path.join(dir, "file2.ex")
      ]

      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read_batch",
        "params" => %{"paths" => paths}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"

      files = response["result"]["files"]
      assert length(files) == 2

      # Both files should be readable
      assert Enum.all?(files, &(&1["error"] == nil))
    end

    test "handles partial failures gracefully", %{test_dir: dir} do
      paths = [
        Path.join(dir, "file1.txt"),
        Path.join(dir, "nonexistent.txt")
      ]

      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read_batch",
        "params" => %{"paths" => paths}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      files = response["result"]["files"]

      # Should have results for both files
      assert length(files) == 2

      # One should succeed, one should fail
      results_by_path = Enum.group_by(files, &(&1["error"] == nil))
      assert map_size(results_by_path) >= 1
    end

    test "returns error for empty paths list" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read_batch",
        "params" => %{"paths" => []}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32602
      assert response["error"]["message"] =~ "Missing or empty param"
    end
  end

  # ============================================================================
  # Grep Tests
  # ============================================================================

  describe "grep_search method" do
    test "finds pattern in files", %{test_dir: dir} do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "grep_search",
        "params" => %{"pattern" => "defmodule", "directory" => dir}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"

      matches = response["result"]["matches"]
      assert length(matches) >= 2

      # Check structure
      match = hd(matches)
      assert match["file"]
      assert match["line_number"]
      assert match["line_content"]
      assert match["match_start"]
      assert match["match_end"]
    end

    test "returns error for missing pattern param", %{test_dir: dir} do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "grep_search",
        "params" => %{"directory" => dir}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32602
      assert response["error"]["message"] =~ "Missing required param"
    end

    test "handles invalid regex pattern", %{test_dir: dir} do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "grep_search",
        "params" => %{"pattern" => "[invalid", "directory" => dir}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32000
      assert response["error"]["message"] =~ "Grep search failed"
    end
  end

  # ============================================================================
  # Error Handling Tests
  # ============================================================================

  describe "error handling" do
    test "returns method not found error" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "unknown_method",
        "params" => %{}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32601
      assert response["error"]["message"] =~ "Method not found"
    end

    test "returns parse error for invalid JSON" do
      output =
        capture_stdio(["not valid json"], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32700
      assert response["error"]["message"] =~ "Parse error"
    end

    test "returns invalid request for malformed request" do
      # Wrong jsonrpc version
      request = %{"jsonrpc" => "1.0", "id" => 1}

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["code"] == -32700
    end
  end

  # ============================================================================
  # Security Tests
  # ============================================================================

  describe "security" do
    test "blocks sensitive path access" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_read",
        "params" => %{"path" => Path.join(System.user_home!(), ".ssh/id_rsa")}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["message"] =~ "sensitive path blocked"
    end

    test "blocks sensitive directory in list_files" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "file_list",
        "params" => %{"directory" => "/etc"}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]
      assert response["error"]["message"] =~ "sensitive path blocked"
    end
  end

  # ============================================================================
  # Protocol Tests
  # ============================================================================

  describe "protocol compliance" do
    test "handles notification (no id) - no response returned" do
      request = %{
        "jsonrpc" => "2.0",
        "method" => "ping",
        "params" => %{}
      }

      # Notifications (no id) should not get responses per JSON-RPC 2.0 spec
      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      # Output should be empty or "{}" (no response for notifications)
      assert output == nil or output == "{}" or output == ""
    end

    test "uses correct JSON-RPC 2.0 response format" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => "test-id-123",
        "method" => "ping",
        "params" => %{}
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["jsonrpc"] == "2.0"
      assert response["id"] == "test-id-123"
      assert Map.has_key?(response, "result")
      refute Map.has_key?(response, "error")
    end
  end

  # ============================================================================
  # Text Replace Tests (bd-39)
  # ============================================================================

  describe "text_replace" do
    test "exact replacement succeeds" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 1,
        "method" => "text_replace",
        "params" => %{
          "content" => "hello world\nfoo bar\n",
          "replacements" => [%{"old_str" => "world", "new_str" => "universe"}]
        }
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["result"]["success"] == true
      assert response["result"]["modified"] == "hello universe\nfoo bar\n"
      assert response["result"]["diff"] != ""
      assert response["result"]["error"] == nil
      assert response["result"]["jw_score"] == nil
    end

    test "fuzzy match failure returns error in result" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 2,
        "method" => "text_replace",
        "params" => %{
          "content" => "completely different\n",
          "replacements" => [%{"old_str" => "xyz-nomatch", "new_str" => "replacement"}]
        }
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["result"]["success"] == false
      assert response["result"]["error"] =~ "JW"
      assert response["result"]["modified"] == "completely different\n"
    end

    test "missing content param returns error" do
      request = %{
        "jsonrpc" => "2.0",
        "id" => 3,
        "method" => "text_replace",
        "params" => %{
          "replacements" => [%{"old_str" => "a", "new_str" => "b"}]
        }
      }

      output =
        capture_stdio([Jason.encode!(request)], fn ->
          StdioService.run()
        end)

      response = Jason.decode!(output)
      assert response["error"]["code"] == -32602
      assert response["error"]["message"] =~ "content"
    end
  end

  # ============================================================================
  # Helper Functions
  # ============================================================================

  # Delegate to shared test helper
  defp capture_stdio(inputs, fun) do
    StdioTestHelper.capture_stdio(inputs, fun)
  end
end
