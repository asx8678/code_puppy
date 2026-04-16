defmodule Mix.Tasks.CodePuppy.StdioService do
  @moduledoc """
  Run the standalone stdio JSON-RPC transport service.

  This task starts the CodePuppyControl.Transport.StdioService as a
  standalone process, reading JSON-RPC requests from stdin and writing
  responses to stdout.

  ## Usage

      mix code_puppy.stdio_service

  ## Environment Variables

  - `PUP_LOG_LEVEL` - Set log level (debug, info, warn, error). Default: info

  ## Protocol

  The service uses newline-delimited JSON-RPC 2.0:

  **Input (stdin):**
      {"jsonrpc":"2.0","id":1,"method":"file_list","params":{"directory":"."}}\n
  **Output (stdout):**
      {"jsonrpc":"2.0","id":1,"result":{"files":[{"path":"lib","type":"directory"}]}}\n
  ## Supported Methods

  ### Core File Operations
  - `file_list` - List files in a directory
      - params: `{"directory": ".", "recursive": true, "include_hidden": false, "ignore_patterns": [], "max_files": 10000}`
      - returns: `{"files": [{"path": "...", "type": "file|directory", "size": 123, "modified": "..."}]}`

  - `file_read` - Read a single file
      - params: `{"path": "/path/to/file", "start_line": 1, "num_lines": 100}`
      - returns: `{"path": "...", "content": "...", "num_lines": 10, "size": 123, "truncated": false}`

  - `file_read_batch` - Read multiple files
      - params: `{"paths": ["/path/1", "/path/2"], "start_line": 1, "num_lines": 100}`
      - returns: `{"files": [{"path": "...", "content": "...", ...}]}`

  - `grep_search` - Search for patterns in files
      - params: `{"pattern": "regex", "directory": ".", "case_sensitive": true, "max_matches": 1000}`
      - returns: `{"matches": [{"file": "...", "line_number": 1, "line_content": "..."}]}`

  ### Utility
  - `ping` - Health check ping
      - returns: `{"pong": true, "timestamp": "..."}`

  - `health_check` - Detailed health status
      - returns: `{"status": "healthy", "version": "...", "elixir_version": "..."}`

  ## Examples

  Interactive test:
      $ mix code_puppy.stdio_service
      {"jsonrpc":"2.0","id":1,"method":"ping"}
      {"jsonrpc":"2.0","id":1,"result":{"pong":true}}

  From another process:
      $ echo '{"jsonrpc":"2.0","id":1,"method":"ping"}' | mix code_puppy.stdio_service

  ## Comparison with Bridge Mode

  This standalone mode is ideal for:
  - Simple scripts that need fast file operations
  - Testing and development
  - Environments without the full Phoenix application
  - Integration with non-Python languages

  Use the bridge mode (PythonWorker.Port) for:
  - Production with PubSub event distribution
  - Web UI integration
  - Complex run management with Oban jobs
  - Full OTP supervision

  ## Exit Codes

  - 0 - Normal shutdown (EOF on stdin)
  - 1 - Startup error
  - 130 - Interrupted (Ctrl+C)
  """

  use Mix.Task

  @requirements ["app.config"]

  @impl true
  def run(_args) do
    # Ensure the FileOps module is available
    Code.ensure_loaded(CodePuppyControl.FileOps)
    Code.ensure_loaded(CodePuppyControl.Protocol)

    # Start required applications without the full Phoenix stack
    Application.ensure_all_started(:logger)
    Application.ensure_all_started(:jason)

    # Configure logger to use stderr only (not stdout which is for JSON-RPC)
    Logger.configure_backend(:console, device: :stderr)

    :logger.add_handler_filter(:default, :stderr_only, fn log_event, _ ->
      {:log, Map.put(log_event, :io_device, :stderr)}
    end)

    # Give the service a moment to suppress any startup output
    Process.sleep(100)

    # Run the stdio service (blocks until EOF)
    CodePuppyControl.Transport.StdioService.run()

    # Normal exit
    System.halt(0)
  end
end
