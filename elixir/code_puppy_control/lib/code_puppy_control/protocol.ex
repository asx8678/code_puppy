defmodule CodePuppyControl.Protocol do
  @moduledoc """
  JSON-RPC 2.0 protocol encoding and decoding with Content-Length framing.

  This module handles:
  - JSON-RPC 2.0 request/response/notification encoding
  - Content-Length HTTP-style framing for Port communication
  - Batch message support (bd-103)

  ## Framing Format

      Content-Length: <bytes>\r\n

      \r\n

      <json_rpc_message>

  ## Batch Format (bd-103)

  JSON-RPC 2.0 batch format sends an array of messages:

      Content-Length: <bytes>\r\n

      \r\n

      [{"jsonrpc":"2.0","id":1,"method":"file_read","params":{...}},
       {"jsonrpc":"2.0","id":2,"method":"file_list","params":{...}}]
  """

  @type json_rpc_id :: String.t() | integer() | nil
  @type json_rpc_message :: map() | list(map())

  @doc """
  Encodes a JSON-RPC 2.0 request.

  ## Examples

      iex> Protocol.encode_request("initialize", %{"capabilities" => %{}}, "req-1")
      %{"jsonrpc" => "2.0", "id" => "req-1", "method" => "initialize", "params" => %{"capabilities" => %{}}}
  """
  @spec encode_request(String.t(), map(), json_rpc_id()) :: map()
  def encode_request(method, params, id) do
    %{
      "jsonrpc" => "2.0",
      "id" => id,
      "method" => method,
      "params" => params
    }
  end

  @doc """
  Encodes a JSON-RPC 2.0 notification (no id).

  ## Examples

      iex> Protocol.encode_notification("exit", %{"code" => 0})
      %{"jsonrpc" => "2.0", "method" => "exit", "params" => %{"code" => 0}}
  """
  @spec encode_notification(String.t(), map()) :: map()
  def encode_notification(method, params) do
    %{
      "jsonrpc" => "2.0",
      "method" => method,
      "params" => params
    }
  end

  @doc """
  Encodes a JSON-RPC 2.0 success response.

  ## Examples

      iex> Protocol.encode_response(%{"result" => "ok"}, "req-1")
      %{"jsonrpc" => "2.0", "id" => "req-1", "result" => %{"result" => "ok"}}
  """
  @spec encode_response(any(), json_rpc_id()) :: map()
  def encode_response(result, id) do
    %{
      "jsonrpc" => "2.0",
      "id" => id,
      "result" => result
    }
  end

  @doc """
  Encodes a JSON-RPC 2.0 error response.

  ## Examples

      iex> Protocol.encode_error(-32600, "Invalid Request", nil)
      %{"jsonrpc" => "2.0", "id" => nil, "error" => %{"code" => -32600, "message" => "Invalid Request"}}
  """
  @spec encode_error(integer(), String.t(), any(), json_rpc_id()) :: map()
  def encode_error(code, message, data \\ nil, id \\ nil) do
    error = %{
      "code" => code,
      "message" => message
    }

    error = if data, do: Map.put(error, "data", data), else: error

    %{
      "jsonrpc" => "2.0",
      "id" => id,
      "error" => error
    }
  end

  @doc """
  Alias for `encode_request/3`.
  """
  def request(method, params, id), do: encode_request(method, params, id)

  @doc """
  Alias for `encode_notification/2`.
  """
  def notification(method, params), do: encode_notification(method, params)

  @doc """
  Alias for `encode_response/2` with argument order for compatibility.
  """
  def response(id, result), do: encode_response(result, id)

  @doc """
  Alias for `encode_error/4` with simplified signature.
  """
  def error_response(id, code, message) do
    encode_error(code, message, nil, id)
  end

  @doc """
  Decodes a JSON-RPC 2.0 message.

  Returns `{:ok, message}` on success or `{:error, reason}` on failure.

  ## Examples

      iex> Protocol.decode(~s({"jsonrpc":"2.0","id":1,"result":{}}))
      {:ok, %{"jsonrpc" => "2.0", "id" => 1, "result" => %{}}}

      iex> Protocol.decode(~s([{"jsonrpc":"2.0","id":1}]))
      {:ok, [%{"jsonrpc" => "2.0", "id" => 1}]}
  """
  @spec decode(String.t() | binary()) :: {:ok, json_rpc_message()} | {:error, term()}
  def decode(data) when is_binary(data) do
    case Jason.decode(data) do
      {:ok, parsed} when is_map(parsed) ->
        validate_jsonrpc(parsed)

      {:ok, parsed} when is_list(parsed) ->
        # bd-103: Batch message support - validate all messages in array
        validate_batch_jsonrpc(parsed)

      {:error, reason} ->
        {:error, {:invalid_json, reason}}
    end
  end

  @doc """
  Frames a JSON-RPC message with Content-Length header for Port communication.

  ## Examples

      iex> Protocol.frame(%{"jsonrpc" => "2.0", "id" => 1, "method" => "test"})
      "Content-Length: 47\\r\\n\\r\\n{\\"jsonrpc\\":\\"2.0\\",\\"id\\":1,\\"method\\":\\"test\\"}"
  """
  @spec frame(json_rpc_message()) :: String.t()
  def frame(message) do
    body = Jason.encode!(message)
    "Content-Length: #{byte_size(body)}\r\n\r\n#{body}"
  end

  @doc """
  Frames a message with explicit body (for pre-encoded bodies).
  """
  @spec frame_body(String.t()) :: String.t()
  def frame_body(body) when is_binary(body) do
    "Content-Length: #{byte_size(body)}\r\n\r\n#{body}"
  end

  @doc """
  Frames a batch of JSON-RPC messages (bd-103).

  Batching reduces IPC overhead by combining N messages into one write.
  Uses JSON-RPC 2.0 batch format (array of messages).

  ## Examples

      iex> Protocol.frame_batch([%{"jsonrpc" => "2.0", "id" => 1}, %{"jsonrpc" => "2.0", "id" => 2}])
      "Content-Length: 53\\r\\n\\r\\n[{\\"jsonrpc\\":\\"2.0\\",\\"id\\":1},{\\"jsonrpc\\":\\"2.0\\",\\"id\\":2}]"
  """
  @spec frame_batch(list(map())) :: String.t()
  def frame_batch(messages) when is_list(messages) do
    body = Jason.encode!(messages)
    "Content-Length: #{byte_size(body)}\r\n\r\n#{body}"
  end

  @doc """
  Parses framed messages from a buffer, returning parsed messages and remaining buffer.

  Returns `{messages, rest_buffer}` where messages is a list of decoded JSON-RPC messages.

  bd-103: Supports batch messages (JSON array format).

  ## Examples

      iex> Protocol.parse_framed("Content-Length: 26\\r\\n\\r\\n{\\"jsonrpc\\":\\"2.0\\",\\"id\\":1}")
      {[%{"jsonrpc" => "2.0", "id" => 1}], ""}
  """
  @spec parse_framed(String.t()) :: {list(map()), String.t()}
  def parse_framed(buffer) when is_binary(buffer) do
    parse_framed_loop(buffer, [])
  end

  @doc """
  Checks if a decoded message is a notification (has no id).
  """
  @spec notification?(map()) :: boolean()
  def notification?(message) when is_map(message) do
    not Map.has_key?(message, "id")
  end

  @doc """
  Checks if a decoded message is a request (has method and id).
  """
  @spec request?(map()) :: boolean()
  def request?(message) when is_map(message) do
    Map.has_key?(message, "method") and Map.has_key?(message, "id")
  end

  @doc """
  Checks if a decoded message is a response (has id and either result or error).
  """
  @spec response?(map()) :: boolean()
  def response?(message) when is_map(message) do
    Map.has_key?(message, "id") and
      (Map.has_key?(message, "result") or Map.has_key?(message, "error"))
  end

  # Private functions

  defp validate_jsonrpc(%{"jsonrpc" => "2.0"} = message) do
    {:ok, message}
  end

  defp validate_jsonrpc(_) do
    {:error, {:invalid_jsonrpc, "missing or invalid jsonrpc version"}}
  end

  # bd-103: Validate batch of JSON-RPC messages
  defp validate_batch_jsonrpc(messages) when is_list(messages) do
    case Enum.all?(messages, &match?(%{"jsonrpc" => "2.0"}, &1)) do
      true -> {:ok, messages}
      false -> {:error, {:invalid_jsonrpc, "batch contains invalid messages"}}
    end
  end

  defp parse_framed_loop(buffer, acc) do
    case parse_header(buffer) do
      {:ok, content_length, rest} ->
        if byte_size(rest) >= content_length do
          <<body::binary-size(content_length), remaining::binary>> = rest

          case decode(body) do
            {:ok, message} -> parse_framed_loop(remaining, [message | acc])
            {:error, _reason} -> parse_framed_loop(remaining, acc)
          end
        else
          {Enum.reverse(acc), buffer}
        end

      :incomplete ->
        {Enum.reverse(acc), buffer}

      {:error, _reason} ->
        # Skip malformed header and continue
        case String.split(buffer, "\r\n\r\n", parts: 2) do
          [_bad, rest] -> parse_framed_loop(rest, acc)
          _ -> {Enum.reverse(acc), ""}
        end
    end
  end

  defp parse_header(buffer) do
    case :binary.match(buffer, "\r\n\r\n") do
      :nomatch ->
        :incomplete

      {header_end, 4} ->
        header = binary_part(buffer, 0, header_end)
        rest = binary_part(buffer, header_end + 4, byte_size(buffer) - header_end - 4)

        case parse_content_length(header) do
          {:ok, length} -> {:ok, length, rest}
          error -> error
        end
    end
  end

  defp parse_content_length(header) do
    header
    |> String.split("\r\n")
    |> Enum.find_value(fn line ->
      case String.split(line, ":", parts: 2) do
        ["Content-Length", value] ->
          case Integer.parse(String.trim(value)) do
            {length, ""} -> {:ok, length}
            _ -> {:error, :invalid_content_length}
          end

        _ ->
          nil
      end
    end)
    |> case do
      {:ok, _} = result -> result
      nil -> {:error, :missing_content_length}
      error -> error
    end
  end
end
