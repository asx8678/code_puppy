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

  ### Agent Model Pinning
  - `agent_pinning.get` - Get pinned model for an agent
  - `agent_pinning.set` - Set pinned model for an agent
  - `agent_pinning.clear` - Clear pin for an agent
  - `agent_pinning.list` - List all agent-to-model pins

  ### Text Operations
  - `text_fuzzy_match` - Find best matching window using fuzzy matching
  - `text_unified_diff` - Generate unified diff between two strings
  - `text_replace` - Apply replacements with exact/fuzzy matching
  - `hashline_compute` - Compute 2-char hash anchor for a line
  - `hashline_format` - Format text with hashline prefixes
  - `hashline_strip` - Strip hashline prefixes from text
  - `hashline_validate` - Validate hashline anchor

  ### Round-Robin Model
  - `round_robin.get_next` - Get next model, advancing rotation
  - `round_robin.get_current` - Get current model without advancing
  - `round_robin.reset` - Reset rotation to initial position
  - `round_robin.get_state` - Get full rotation state
  - `round_robin.configure` - Configure models and rotation settings
  - `round_robin.list_models` - List configured models

  ### Scheduler Tools (bd-67)
  - `scheduler.list_tasks` - List all scheduled tasks with status
  - `scheduler.create_task` - Create a new scheduled task
  - `scheduler.delete_task` - Delete a task by ID or name
  - `scheduler.toggle_task` - Toggle task enabled/disabled state
  - `scheduler.status` - Get scheduler status
  - `scheduler.run_task` - Run a task immediately
  - `scheduler.view_log` - View task execution history
  - `scheduler.force_check` - Force immediate schedule evaluation

  ### HTTP Client
  - `http.request` - Make HTTP request with retry logic
  - `http.get` - Simple GET request
  - `http.post` - POST request with body

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

  alias CodePuppyControl.AgentModelPinning
  alias CodePuppyControl.FileOps
  alias CodePuppyControl.Protocol
  alias CodePuppyControl.Tools.SchedulerTools
  alias CodePuppyControl.RoundRobinModel

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

  # text_replace - Apply replacements with exact/fuzzy matching (bd-39)
  defp handle_request("text_replace", params, id) do
    content = params["content"]
    replacements_raw = params["replacements"]

    cond do
      is_nil(content) ->
        Protocol.encode_error(-32602, "Missing required param: content", nil, id)

      is_nil(replacements_raw) or not is_list(replacements_raw) ->
        Protocol.encode_error(-32602, "Missing or invalid param: replacements", nil, id)

      true ->
        replacements =
          Enum.map(replacements_raw, fn rep ->
            {rep["old_str"] || "", rep["new_str"] || ""}
          end)

        alias CodePuppyControl.Text.ReplaceEngine

        case ReplaceEngine.replace_in_content(content, replacements) do
          {:ok, %{modified: modified, diff: diff, jw_score: jw_score}} ->
            Protocol.encode_response(
              %{
                "modified" => modified,
                "diff" => diff,
                "success" => true,
                "error" => nil,
                "jw_score" => jw_score
              },
              id
            )

          {:error, %{reason: reason, jw_score: jw_score, original: original}} ->
            Protocol.encode_response(
              %{
                "modified" => original,
                "diff" => "",
                "success" => false,
                "error" => reason,
                "jw_score" => jw_score
              },
              id
            )
        end
    end
  end

  # text_fuzzy_match - Find best matching window using fuzzy matching (bd-41)
  defp handle_request("text_fuzzy_match", params, id) do
    haystack_lines = params["haystack_lines"]
    needle = params["needle"]

    cond do
      is_nil(haystack_lines) or not is_list(haystack_lines) ->
        Protocol.encode_error(-32602, "Missing or invalid param: haystack_lines", nil, id)

      is_nil(needle) or not is_binary(needle) ->
        Protocol.encode_error(-32602, "Missing or invalid param: needle", nil, id)

      true ->
        alias CodePuppyControl.Text.FuzzyMatch

        case FuzzyMatch.fuzzy_match_window(haystack_lines, needle) do
          {:ok,
           %{
             matched_text: matched_text,
             start_line: start_line,
             end_line: end_line,
             similarity: similarity
           }} ->
            Protocol.encode_response(
              %{
                "matched_text" => matched_text,
                "start" => start_line,
                "end" => end_line,
                "score" => similarity
              },
              id
            )

          :no_match ->
            Protocol.encode_response(
              %{"matched_text" => nil, "start" => 0, "end" => nil, "score" => 0.0},
              id
            )
        end
    end
  end

  # text_unified_diff - Generate unified diff between two strings (bd-41)
  defp handle_request("text_unified_diff", params, id) do
    old = params["old"]
    new = params["new"]

    cond do
      is_nil(old) or not is_binary(old) ->
        Protocol.encode_error(-32602, "Missing or invalid param: old", nil, id)

      is_nil(new) or not is_binary(new) ->
        Protocol.encode_error(-32602, "Missing or invalid param: new", nil, id)

      true ->
        alias CodePuppyControl.Text.Diff

        context_lines = params["context_lines"] || 3
        from_file = params["from_file"] || ""
        to_file = params["to_file"] || ""

        result =
          Diff.unified_diff(old, new,
            context_lines: context_lines,
            from_file: from_file,
            to_file: to_file
          )

        Protocol.encode_response(%{"diff" => result}, id)
    end
  end

  # hashline_compute - Compute 2-char hash anchor for a line (bd-88)
  defp handle_request("hashline_compute", params, id) do
    idx = params["idx"]
    line = params["line"]

    cond do
      is_nil(idx) or not is_integer(idx) ->
        Protocol.encode_error(-32602, "Missing or invalid param: idx", nil, id)

      is_nil(line) or not is_binary(line) ->
        Protocol.encode_error(-32602, "Missing or invalid param: line", nil, id)

      true ->
        hash = CodePuppyControl.HashlineNif.compute_line_hash(idx, line)
        Protocol.encode_response(%{"hash" => hash}, id)
    end
  end

  # hashline_format - Format text with hashline prefixes (bd-88)
  defp handle_request("hashline_format", params, id) do
    text = params["text"]
    start_line = params["start_line"] || 1

    cond do
      is_nil(text) or not is_binary(text) ->
        Protocol.encode_error(-32602, "Missing or invalid param: text", nil, id)

      true ->
        result = CodePuppyControl.HashlineNif.format_hashlines(text, start_line)
        Protocol.encode_response(%{"formatted" => result}, id)
    end
  end

  # hashline_strip - Strip hashline prefixes from text (bd-88)
  defp handle_request("hashline_strip", params, id) do
    text = params["text"]

    cond do
      is_nil(text) or not is_binary(text) ->
        Protocol.encode_error(-32602, "Missing or invalid param: text", nil, id)

      true ->
        result = CodePuppyControl.HashlineNif.strip_hashline_prefixes(text)
        Protocol.encode_response(%{"stripped" => result}, id)
    end
  end

  # hashline_validate - Validate hashline anchor (bd-88)
  defp handle_request("hashline_validate", params, id) do
    idx = params["idx"]
    line = params["line"]
    expected_hash = params["expected_hash"]

    cond do
      is_nil(idx) or not is_integer(idx) ->
        Protocol.encode_error(-32602, "Missing or invalid param: idx", nil, id)

      is_nil(line) or not is_binary(line) ->
        Protocol.encode_error(-32602, "Missing or invalid param: line", nil, id)

      is_nil(expected_hash) or not is_binary(expected_hash) ->
        Protocol.encode_error(-32602, "Missing or invalid param: expected_hash", nil, id)

      true ->
        valid = CodePuppyControl.HashlineNif.validate_hashline_anchor(idx, line, expected_hash)
        Protocol.encode_response(%{"valid" => valid}, id)
    end
  end

  # ============================================================================
  # Runtime State Operations (bd-75)
  # ============================================================================

  # runtime_get_autosave_id - Get current autosave session ID
  defp handle_request("runtime_get_autosave_id", _params, id) do
    autosave_id = CodePuppyControl.RuntimeState.get_current_autosave_id()
    Protocol.encode_response(%{"autosave_id" => autosave_id}, id)
  end

  # runtime_get_autosave_session_name - Get full session name
  defp handle_request("runtime_get_autosave_session_name", _params, id) do
    session_name = CodePuppyControl.RuntimeState.get_current_autosave_session_name()
    Protocol.encode_response(%{"session_name" => session_name}, id)
  end

  # runtime_rotate_autosave_id - Force new autosave ID
  defp handle_request("runtime_rotate_autosave_id", _params, id) do
    new_id = CodePuppyControl.RuntimeState.rotate_autosave_id()
    Protocol.encode_response(%{"autosave_id" => new_id}, id)
  end

  # runtime_set_autosave_from_session - Set ID from session name
  defp handle_request("runtime_set_autosave_from_session", params, id) do
    session_name = params["session_name"]

    if is_nil(session_name) or not is_binary(session_name) do
      Protocol.encode_error(-32602, "Missing or invalid param: session_name", nil, id)
    else
      set_id = CodePuppyControl.RuntimeState.set_current_autosave_from_session_name(session_name)
      Protocol.encode_response(%{"autosave_id" => set_id}, id)
    end
  end

  # runtime_reset_autosave_id - Reset autosave ID to nil
  defp handle_request("runtime_reset_autosave_id", _params, id) do
    :ok = CodePuppyControl.RuntimeState.reset_autosave_id()
    Protocol.encode_response(%{"reset" => true}, id)
  end

  # runtime_get_session_model - Get cached session model
  defp handle_request("runtime_get_session_model", _params, id) do
    model = CodePuppyControl.RuntimeState.get_session_model()
    Protocol.encode_response(%{"session_model" => model}, id)
  end

  # runtime_set_session_model - Set session model
  defp handle_request("runtime_set_session_model", params, id) do
    model = params["model"]
    :ok = CodePuppyControl.RuntimeState.set_session_model(model)
    Protocol.encode_response(%{"session_model" => model}, id)
  end

  # runtime_reset_session_model - Reset session model cache
  defp handle_request("runtime_reset_session_model", _params, id) do
    :ok = CodePuppyControl.RuntimeState.reset_session_model()
    Protocol.encode_response(%{"reset" => true}, id)
  end

  # runtime_get_state - Get full runtime state for introspection
  defp handle_request("runtime_get_state", _params, id) do
    state = CodePuppyControl.RuntimeState.get_state()

    result = %{
      "autosave_id" => state.autosave_id,
      "session_model" => state.session_model,
      "session_start_time" =>
        case DateTime.to_iso8601(state.session_start_time) do
          {:ok, str} -> str
          str when is_binary(str) -> str
          _ -> nil
        end
    }

    Protocol.encode_response(result, id)
  end

  # ============================================================================
  # Agent Model Pinning Operations (bd-72)
  # ============================================================================

  # agent_pinning.get - Get pinned model for an agent (bd-72)
  defp handle_request("agent_pinning.get", params, id) do
    agent_name = params["agent_name"]

    if is_nil(agent_name) or not is_binary(agent_name) do
      Protocol.encode_error(-32602, "Missing or invalid param: agent_name", nil, id)
    else
      model = AgentModelPinning.get_pinned_model(agent_name)
      Protocol.encode_response(%{"agent_name" => agent_name, "model" => model}, id)
    end
  end

  # agent_pinning.set - Set pinned model for an agent (bd-72)
  defp handle_request("agent_pinning.set", params, id) do
    agent_name = params["agent_name"]
    model = params["model"]

    cond do
      is_nil(agent_name) or not is_binary(agent_name) ->
        Protocol.encode_error(-32602, "Missing or invalid param: agent_name", nil, id)

      is_nil(model) or not is_binary(model) ->
        Protocol.encode_error(-32602, "Missing or invalid param: model", nil, id)

      true ->
        :ok = AgentModelPinning.set_pinned_model(agent_name, model)
        Protocol.encode_response(%{"agent_name" => agent_name, "model" => model}, id)
    end
  end

  # agent_pinning.clear - Clear pin for an agent (bd-72)
  defp handle_request("agent_pinning.clear", params, id) do
    agent_name = params["agent_name"]

    if is_nil(agent_name) or not is_binary(agent_name) do
      Protocol.encode_error(-32602, "Missing or invalid param: agent_name", nil, id)
    else
      :ok = AgentModelPinning.clear_pinned_model(agent_name)
      Protocol.encode_response(%{"agent_name" => agent_name, "cleared" => true}, id)
    end
  end

  # agent_pinning.list - List all agent-to-model pins (bd-72)
  defp handle_request("agent_pinning.list", _params, id) do
    pins = AgentModelPinning.list_pins()
    pin_list = Enum.map(pins, fn {agent, model} -> %{"agent_name" => agent, "model" => model} end)
    Protocol.encode_response(%{"pins" => pin_list, "count" => length(pin_list)}, id)
  end

  # ============================================================================
  # Scheduler Tools (bd-67)
  # ============================================================================

  # scheduler.list_tasks - List all scheduled tasks with status
  defp handle_request("scheduler.list_tasks", _params, id) do
    result = SchedulerTools.list_tasks()
    Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
  end

  # ============================================================================
  # HTTP Client Operations (bd-69)
  # ============================================================================

  # http.get - Simple GET request
  defp handle_request("http.get", params, id) do
    url = params["url"]

    if is_nil(url) or not is_binary(url) do
      Protocol.encode_error(-32602, "Missing or invalid param: url", nil, id)
    else
      opts = params_to_http_opts(params)

      case CodePuppyControl.HttpClient.get(url, opts) do
        {:ok, response} ->
          Protocol.encode_response(serialize_http_response(response), id)

        {:error, reason} ->
          Protocol.encode_error(
            -32000,
            "HTTP request failed: #{format_error(reason)}",
            nil,
            id
          )
      end
    end
  end

  # http.post - POST request
  defp handle_request("http.post", params, id) do
    url = params["url"]
    body = params["body"]

    if is_nil(url) or not is_binary(url) do
      Protocol.encode_error(-32602, "Missing or invalid param: url", nil, id)
    else
      opts = params_to_http_opts(params)
      opts = if body, do: Keyword.put(opts, :body, body), else: opts

      case CodePuppyControl.HttpClient.post(url, opts) do
        {:ok, response} ->
          Protocol.encode_response(serialize_http_response(response), id)

        {:error, reason} ->
          Protocol.encode_error(
            -32000,
            "HTTP request failed: #{format_error(reason)}",
            nil,
            id
          )
      end
    end
  end

  # http.request - Full request with method selection
  defp handle_request("http.request", params, id) do
    method_str = params["method"] || "GET"
    url = params["url"]
    body = params["body"]

    if is_nil(url) or not is_binary(url) do
      Protocol.encode_error(-32602, "Missing or invalid param: url", nil, id)
    else
      method = parse_http_method(method_str)
      opts = params_to_http_opts(params)
      opts = if body, do: Keyword.put(opts, :body, body), else: opts

      case CodePuppyControl.HttpClient.request(method, url, opts) do
        {:ok, response} ->
          Protocol.encode_response(serialize_http_response(response), id)

        {:error, reason} ->
          Protocol.encode_error(
            -32000,
            "HTTP request failed: #{format_error(reason)}",
            nil,
            id
          )
      end
    end
  end

  # scheduler.create_task - Create a new scheduled task
  defp handle_request("scheduler.create_task", params, id) do
    attrs =
      %{
        name: params["name"],
        prompt: params["prompt"],
        agent_name: params["agent_name"] || params["agent"],
        model: params["model"],
        schedule_type: params["schedule_type"] || "interval",
        schedule_value: params["schedule_value"],
        working_directory: params["working_directory"] || "."
      }
      |> Enum.reject(fn {_, v} -> is_nil(v) end)
      |> Map.new()

    result = SchedulerTools.create_task(attrs)
    Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
  end

  # scheduler.delete_task - Delete a task by ID or name
  defp handle_request("scheduler.delete_task", params, id) do
    task_id = params["task_id"] || params["id"]

    if is_nil(task_id) do
      Protocol.encode_error(-32602, "Missing required param: task_id", nil, id)
    else
      result = SchedulerTools.delete_task(task_id)
      Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
    end
  end

  # scheduler.toggle_task - Toggle task enabled/disabled state
  defp handle_request("scheduler.toggle_task", params, id) do
    task_id = params["task_id"] || params["id"]

    if is_nil(task_id) do
      Protocol.encode_error(-32602, "Missing required param: task_id", nil, id)
    else
      result = SchedulerTools.toggle_task(task_id)
      Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
    end
  end

  # scheduler.status - Get scheduler status
  defp handle_request("scheduler.status", _params, id) do
    result = SchedulerTools.scheduler_status()
    Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
  end

  # scheduler.run_task - Run a task immediately
  defp handle_request("scheduler.run_task", params, id) do
    task_id = params["task_id"] || params["id"]

    if is_nil(task_id) do
      Protocol.encode_error(-32602, "Missing required param: task_id", nil, id)
    else
      result = SchedulerTools.run_task(task_id)
      Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
    end
  end

  # scheduler.view_log - View task execution history
  defp handle_request("scheduler.view_log", params, id) do
    task_id = params["task_id"] || params["id"]
    lines = params["lines"] || 10

    if is_nil(task_id) do
      Protocol.encode_error(-32602, "Missing required param: task_id", nil, id)
    else
      result = SchedulerTools.view_log(task_id, lines)
      Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
    end
  end

  # scheduler.force_check - Force immediate schedule evaluation
  defp handle_request("scheduler.force_check", _params, id) do
    result = SchedulerTools.force_check()
    Protocol.encode_response(%{"result" => result, "type" => "markdown"}, id)
  end


  # ============================================================================
  # Round-Robin Model Operations (bd-71)
  # ============================================================================

  # round_robin.get_next - Get next model, advancing rotation (bd-71)
  defp handle_request("round_robin.get_next", _params, id) do
    model = RoundRobinModel.advance_and_get()
    Protocol.encode_response(%{"model" => model}, id)
  end

  # round_robin.get_current - Get current model without advancing (bd-71)
  defp handle_request("round_robin.get_current", _params, id) do
    model = RoundRobinModel.get_current_model()
    Protocol.encode_response(%{"model" => model}, id)
  end

  # round_robin.reset - Reset rotation to initial position (bd-71)
  defp handle_request("round_robin.reset", _params, id) do
    :ok = RoundRobinModel.reset()
    Protocol.encode_response(%{"reset" => true}, id)
  end

  # round_robin.get_state - Get full rotation state (bd-71)
  defp handle_request("round_robin.get_state", _params, id) do
    state = RoundRobinModel.get_state()

    result =
      if state do
        %{
          "models" => state.models,
          "current_index" => state.current_index,
          "rotate_every" => state.rotate_every,
          "request_count" => state.request_count,
          "current_model" => Enum.at(state.models, state.current_index)
        }
      else
        %{
          "models" => [],
          "current_index" => 0,
          "rotate_every" => 1,
          "request_count" => 0,
          "current_model" => nil
        }
      end

    Protocol.encode_response(result, id)
  end

  # round_robin.configure - Configure models and rotation settings (bd-71)
  defp handle_request("round_robin.configure", params, id) do
    models = params["models"]
    rotate_every = params["rotate_every"] || 1

    cond do
      is_nil(models) or not is_list(models) ->
        Protocol.encode_error(
          -32602,
          "Missing or invalid param: models (must be a list)",
          nil,
          id
        )

      models == [] ->
        Protocol.encode_error(-32602, "Invalid param: models cannot be empty", nil, id)

      rotate_every < 1 ->
        Protocol.encode_error(-32602, "Invalid param: rotate_every must be >= 1", nil, id)

      true ->
        case RoundRobinModel.configure(models: models, rotate_every: rotate_every) do
          :ok ->
            Protocol.encode_response(
              %{"configured" => true, "models" => models, "rotate_every" => rotate_every},
              id
            )

          {:error, reason} ->
            Protocol.encode_error(-32602, "Configuration failed: #{reason}", nil, id)
        end
    end
  end

  # round_robin.list_models - List configured models
  defp handle_request("round_robin.list_models", _params, id) do
    models = RoundRobinModel.list_models()
    Protocol.encode_response(%{"models" => models, "count" => length(models)}, id)
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
  # HTTP Helpers
  # ============================================================================

  # Map of known HTTP methods - prevents atom exhaustion from user input (bd-69)
  @http_methods %{
    "get" => :get,
    "post" => :post,
    "put" => :put,
    "patch" => :patch,
    "delete" => :delete,
    "head" => :head,
    "options" => :options
  }

  defp parse_http_method(method) when is_binary(method) do
    # Use safe mapping instead of String.to_atom to prevent atom exhaustion
    Map.get(@http_methods, String.downcase(method), :get)
  end

  defp parse_http_method(method) when is_atom(method), do: method

  defp params_to_http_opts(params) do
    opts = []

    opts =
      if params["headers"],
        do: [{:headers, normalize_headers(params["headers"])} | opts],
        else: opts

    opts = if params["timeout"], do: [{:timeout, params["timeout"]} | opts], else: opts
    opts = if params["retries"], do: [{:retries, params["retries"]} | opts], else: opts
    opts = if params["model_name"], do: [{:model_name, params["model_name"]} | opts], else: opts
    opts
  end

  defp normalize_headers(headers) when is_map(headers) do
    Enum.map(headers, fn {k, v} -> {to_string(k), to_string(v)} end)
  end

  defp normalize_headers(headers) when is_list(headers) do
    Enum.map(headers, fn
      {k, v} -> {to_string(k), to_string(v)}
      [k, v] -> {to_string(k), to_string(v)}
    end)
  end

  defp normalize_headers(_), do: []

  defp serialize_http_response(%{status: status, body: body, headers: headers}) do
    %{
      "status" => status,
      "body" => body,
      "headers" => Enum.map(headers, fn {k, v} -> [k, v] end)
    }
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
