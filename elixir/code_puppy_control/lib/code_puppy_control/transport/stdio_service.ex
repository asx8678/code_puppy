defmodule CodePuppyControl.Transport.StdioService do
  @moduledoc """
  Standalone stdio JSON-RPC transport service for FileOps.

  This module provides a standalone Elixir transport that can be run
  outside of the full Phoenix/Web application stack. It communicates
  via stdin/stdout using newline-delimited JSON-RPC 2.0 messages.

  ## Usage

  Run from command line:
      mix code_puppy.stdio_service

  Or as an escript (if configured):
      code_puppy_stdio

  ## Protocol

  Uses newline-delimited JSON-RPC 2.0:

  **Request:**
      {"jsonrpc":"2.0","id":1,"method":"file_list","params":{"directory":"."}}

  **Response:**
      {"jsonrpc":"2.0","id":1,"result":{"files":[{"path":"lib","type":"directory",...}]}}

  **Error:**
      {"jsonrpc":"2.0","id":1,"error":{"code":-32000,"message":"Path not found"}}

  ## Comparison with Bridge Mode

  | Aspect | Bridge Mode (Port) | Standalone (StdioService) |
  |--------|-------------------|---------------------------|
  | Runtime | Inside Phoenix app | Independent process |
  | Framing | Content-Length | Newline-delimited |
  | Start | Supervisor-managed | CLI/manual |
  | Use case | Production with PubSub | Scripts, simple workflows |
  | Dependencies | Full OTP app | Minimal (FileOps, Protocol) |

  ## Supported Methods

  ### File Operations
  - `file_list` - List files in directory
  - `file_read` - Read single file contents
  - `file_read_batch` - Read multiple files
  - `grep_search` - Search for patterns in files

  ### Utility
  - `health_check` - Service health status
  - `ping` - Simple ping/pong

  ## Security

  All file operations use the same `FileOps.sensitive_path?/1` validation
  as the bridge mode. Access to SSH keys, cloud credentials, and system
  secrets is blocked.

  ## Configuration

  Set via environment variable:
  - `PUP_LOG_LEVEL` - Service log level (default: info)
  """

  use GenServer

  require Logger

  alias CodePuppyControl.FileOps
  alias CodePuppyControl.Protocol

  defstruct [:io_device, :buffer, :request_counter]

  @type t :: %__MODULE__{
          io_device: pid() | nil,
          buffer: String.t(),
          request_counter: non_neg_integer()
        }

  @default_io_device :stdio

  # ============================================================================
  # Client API
  # ============================================================================

  @doc """
  Starts the stdio service.

  Options:
  - `:io_device` - The IO device to use (default: :stdio for stdin/stdout)
  - `:buffer` - Initial buffer content for testing
  """
  def start_link(opts \\ []) do
    GenServer.start_link(__MODULE__, opts, name: __MODULE__)
  end

  @doc """
  Starts the stdio service in a blocking mode suitable for CLI execution.
  Waits for the service to complete (EOF on stdin).
  """
  def run(opts \\ []) do
    {:ok, pid} = start_link(opts)
    ref = Process.monitor(pid)

    receive do
      {:DOWN, ^ref, :process, _pid, _reason} ->
        :ok
    end
  end

  # ============================================================================
  # Server Callbacks
  # ============================================================================

  @impl true
  def init(opts) do
    io_device = Keyword.get(opts, :io_device, @default_io_device)
    buffer = Keyword.get(opts, :buffer, "")

    # Set up logger from environment
    configure_logging()

    # Request stdin line mode for efficient reading
    if io_device == :stdio do
      :io.setopts(:standard_io, encoding: :unicode, binary: true)
    end

    # Log to stderr, not stdout (stdout is for JSON-RPC protocol)
    IO.puts(:stderr, "CodePuppy StdioService starting (pid: #{System.pid()})")

    # Schedule initial read
    send(self(), :read_line)

    state = %__MODULE__{
      io_device: io_device,
      buffer: buffer,
      request_counter: 0
    }

    {:ok, state}
  end

  @impl true
  def handle_info(:read_line, %{io_device: io_device} = state) do
    # Read a line from stdin
    case read_line(io_device) do
      {:ok, line} ->
        new_state = process_line(line, state)
        # Schedule next read
        send(self(), :read_line)
        {:noreply, new_state}

      :eof ->
        Logger.info("StdioService received EOF, shutting down")
        {:stop, :normal, state}

      {:error, reason} ->
        Logger.error("Error reading from stdin: #{inspect(reason)}")
        send(self(), :read_line)
        {:noreply, state}
    end
  end

  @impl true
  def handle_info({:DOWN, _ref, :process, _pid, reason}, state) do
    Logger.warning("Linked process exited: #{inspect(reason)}")
    {:noreply, state}
  end

  @impl true
  def handle_info(msg, state) do
    Logger.debug("Unexpected message: #{inspect(msg)}")
    {:noreply, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp read_line(:stdio) do
    case :io.get_line(~c"") do
      :eof -> :eof
      {:error, reason} -> {:error, reason}
      line -> {:ok, to_string(line)}
    end
  end

  defp read_line(device) when is_pid(device) do
    case :file.read_line(device) do
      :eof -> :eof
      {:error, reason} -> {:error, reason}
      {:ok, line} -> {:ok, to_string(line)}
    end
  end

  defp process_line(line, state) do
    line = String.trim_trailing(line, "\n")

    if line == "" do
      state
    else
      case Protocol.decode(line) do
        {:ok, message} ->
          response = handle_message(message)
          # Per JSON-RPC 2.0 spec: "The Server MUST NOT reply to a Notification"
          # Notifications have no "id" field
          unless notification?(message) do
            write_response(response, state.io_device)
          end

          %{state | request_counter: state.request_counter + 1}

        {:error, reason} ->
          error_response =
            Protocol.encode_error(
              -32700,
              "Parse error: #{inspect(reason)}",
              nil,
              extract_id(line)
            )

          write_response(error_response, state.io_device)
          state
      end
    end
  end

  # Check if message is a notification (no "id" field per JSON-RPC 2.0 spec)
  defp notification?(%{"id" => _}), do: false
  defp notification?(%{}), do: true
  defp notification?(messages) when is_list(messages), do: false
  defp notification?(_), do: true

  # Batch request handling (array of messages)
  defp handle_message(messages) when is_list(messages) do
    Enum.map(messages, &handle_single_message/1)
  end

  # Single message handling
  defp handle_message(message) when is_map(message) do
    handle_single_message(message)
  end

  defp handle_single_message(%{"id" => id, "method" => method, "params" => params}) do
    handle_request(method, params, id)
  end

  defp handle_single_message(%{"id" => id, "method" => method}) do
    # Handle methods with no params
    handle_request(method, %{}, id)
  end

  defp handle_single_message(%{"method" => method, "params" => params}) do
    # Notification (no id) - handle but don't send response
    Logger.debug("Received notification: #{method}")
    handle_request(method, params, nil)
  end

  defp handle_single_message(%{"method" => method}) do
    Logger.debug("Received notification: #{method}")
    handle_request(method, %{}, nil)
  end

  defp handle_single_message(message) do
    Protocol.encode_error(
      -32600,
      "Invalid Request",
      %{"received" => message},
      nil
    )
  end

  # ============================================================================
  # Request Handlers
  # ============================================================================

  defp handle_request("ping", _params, id) do
    Protocol.encode_response(%{"pong" => true, "timestamp" => now_iso8601()}, id)
  end

  defp handle_request("health_check", _params, id) do
    health = %{
      "status" => "healthy",
      "version" => version(),
      "elixir_version" => System.version(),
      "otp_version" => :erlang.system_info(:otp_release) |> to_string(),
      "timestamp" => now_iso8601()
    }

    Protocol.encode_response(health, id)
  end

  # file_list - List files in directory
  defp handle_request("file_list", params, id) do
    directory = params["directory"] || "."
    opts = params_to_list_opts(params)

    case FileOps.list_files(directory, opts) do
      {:ok, files} ->
        serializable = serialize_file_list(files)
        Protocol.encode_response(%{"files" => serializable}, id)

      {:error, reason} ->
        Protocol.encode_error(
          -32000,
          "File list failed: #{format_error(reason)}",
          nil,
          id
        )
    end
  end

  # file_read - Read single file
  defp handle_request("file_read", params, id) do
    path = params["path"]

    if is_nil(path) do
      Protocol.encode_error(-32602, "Missing required param: path", nil, id)
    else
      opts = params_to_read_opts(params)

      case FileOps.read_file(path, opts) do
        {:ok, result} ->
          Protocol.encode_response(serialize_read_result(result), id)

        {:error, reason} ->
          Protocol.encode_error(
            -32000,
            "File read failed: #{format_error(reason)}",
            nil,
            id
          )
      end
    end
  end

  # file_read_batch - Read multiple files
  defp handle_request("file_read_batch", params, id) do
    paths = params["paths"] || []

    if paths == [] do
      Protocol.encode_error(-32602, "Missing or empty param: paths", nil, id)
    else
      opts = params_to_read_opts(params)

      # FileOps.read_files/2 always returns {:ok, results} - errors are in the results
      {:ok, results} = FileOps.read_files(paths, opts)
      serialized = Enum.map(results, &serialize_read_result/1)
      Protocol.encode_response(%{"files" => serialized}, id)
    end
  end

  # grep_search - Search for patterns
  defp handle_request("grep_search", params, id) do
    pattern = params["search_string"] || params["pattern"]
    directory = params["directory"] || "."

    if is_nil(pattern) do
      Protocol.encode_error(-32602, "Missing required param: pattern", nil, id)
    else
      opts = params_to_grep_opts(params)

      case FileOps.grep(pattern, directory, opts) do
        {:ok, matches} ->
          Protocol.encode_response(%{"matches" => serialize_grep_matches(matches)}, id)

        {:error, reason} ->
          Protocol.encode_error(
            -32000,
            "Grep search failed: #{format_error(reason)}",
            nil,
            id
          )
      end
    end
  end

  # Method not found handler
  defp handle_request(method, _params, id) do
    Protocol.encode_error(
      -32601,
      "Method not found: #{method}",
      nil,
      id
    )
  end

  # ============================================================================
  # Serialization Helpers
  # ============================================================================

  defp serialize_file_list(files) do
    Enum.map(files, fn file ->
      file
      |> Map.update(:modified, nil, fn dt ->
        case DateTime.to_iso8601(dt) do
          {:ok, str} -> str
          str when is_binary(str) -> str
          _ -> nil
        end
      end)
      |> Map.update(:type, nil, fn t ->
        if is_atom(t), do: Atom.to_string(t), else: t
      end)
    end)
  end

  defp serialize_read_result(result) do
    %{
      "path" => result.path,
      "content" => result.content,
      "num_lines" => result.num_lines,
      "size" => result.size,
      "truncated" => result.truncated,
      "error" => result.error
    }
  end

  defp serialize_grep_matches(matches) do
    Enum.map(matches, fn m ->
      %{
        "file" => m.file,
        "line_number" => m.line_number,
        "line_content" => m.line_content,
        "match_start" => m.match_start,
        "match_end" => m.match_end
      }
    end)
  end

  # ============================================================================
  # Parameter Conversion
  # ============================================================================

  defp params_to_list_opts(params) do
    [
      recursive: Map.get(params, "recursive", true),
      include_hidden: Map.get(params, "include_hidden", false),
      ignore_patterns: Map.get(params, "ignore_patterns", []),
      max_files: Map.get(params, "max_files", 10_000)
    ]
  end

  defp params_to_read_opts(params) do
    opts = []
    opts = if params["start_line"], do: [{:start_line, params["start_line"]} | opts], else: opts
    opts = if params["num_lines"], do: [{:num_lines, params["num_lines"]} | opts], else: opts
    opts
  end

  defp params_to_grep_opts(params) do
    [
      case_sensitive: Map.get(params, "case_sensitive", true),
      max_matches: Map.get(params, "max_matches", 1_000),
      file_pattern: Map.get(params, "file_pattern", "*"),
      context_lines: Map.get(params, "context_lines", 0)
    ]
  end

  # ============================================================================
  # Output
  # ============================================================================

  defp write_response(response, io_device) do
    framed = Protocol.frame_newline(response)
    write_line(framed, io_device)
  end

  defp write_line(data, :stdio) do
    IO.write(data)
    :ok
  end

  defp write_line(data, device) when is_pid(device) do
    :file.write(device, data)
  end

  # ============================================================================
  # Utilities
  # ============================================================================

  defp extract_id(line) do
    case Jason.decode(line) do
      {:ok, %{"id" => id}} -> id
      _ -> nil
    end
  rescue
    _ -> nil
  end

  defp format_error(reason) when is_binary(reason), do: reason
  defp format_error(reason), do: inspect(reason)

  defp now_iso8601 do
    DateTime.utc_now() |> DateTime.to_iso8601()
  end

  defp version do
    Application.spec(:code_puppy_control, :vsn)
    |> to_string()
  end

  # Map of known log levels - prevents atom exhaustion from user input
  @log_levels %{
    "debug" => :debug,
    "info" => :info,
    "warn" => :warn,
    "warning" => :warn,
    "error" => :error
  }

  defp configure_logging do
    level_str = System.get_env("PUP_LOG_LEVEL", "info")
    # Use safe mapping instead of String.to_atom to prevent atom exhaustion
    log_level = Map.get(@log_levels, String.downcase(level_str), :info)
    Logger.configure(level: log_level)

    # Ensure logs go to stderr, not stdout, to avoid interfering with JSON-RPC protocol
    Logger.configure_backend(:console,
      device: :standard_error,
      format: "$time [$level] $message\n"
    )
  end
end
