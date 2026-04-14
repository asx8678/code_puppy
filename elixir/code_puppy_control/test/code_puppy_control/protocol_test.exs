defmodule CodePuppyControl.ProtocolTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.Protocol

  describe "encode_request/3" do
    test "encodes a JSON-RPC 2.0 request" do
      result = Protocol.encode_request("initialize", %{"foo" => "bar"}, 1)

      assert result == %{
               "jsonrpc" => "2.0",
               "id" => 1,
               "method" => "initialize",
               "params" => %{"foo" => "bar"}
             }
    end

    test "handles string ids" do
      result = Protocol.encode_request("test", %{}, "req-123")

      assert result["id"] == "req-123"
    end
  end

  describe "encode_notification/2" do
    test "encodes a JSON-RPC 2.0 notification (no id)" do
      result = Protocol.encode_notification("exit", %{"code" => 0})

      assert result == %{
               "jsonrpc" => "2.0",
               "method" => "exit",
               "params" => %{"code" => 0}
             }

      assert not Map.has_key?(result, "id")
    end
  end

  describe "encode_response/2" do
    test "encodes a JSON-RPC 2.0 success response" do
      result = Protocol.encode_response(%{"status" => "ok"}, 1)

      assert result == %{
               "jsonrpc" => "2.0",
               "id" => 1,
               "result" => %{"status" => "ok"}
             }
    end
  end

  describe "encode_error/4" do
    test "encodes a JSON-RPC 2.0 error without data" do
      result = Protocol.encode_error(-32600, "Invalid Request", nil, 1)

      assert result == %{
               "jsonrpc" => "2.0",
               "id" => 1,
               "error" => %{"code" => -32600, "message" => "Invalid Request"}
             }
    end

    test "encodes a JSON-RPC 2.0 error with data" do
      result = Protocol.encode_error(-32600, "Invalid Request", %{"details" => "extra"}, 1)

      assert result["error"]["data"] == %{"details" => "extra"}
    end
  end

  describe "decode/1" do
    test "decodes valid JSON-RPC message" do
      json = ~s({"jsonrpc":"2.0","id":1,"result":{}})
      assert {:ok, decoded} = Protocol.decode(json)
      assert decoded["jsonrpc"] == "2.0"
      assert decoded["id"] == 1
    end

    test "returns error for invalid JSON" do
      assert {:error, {:invalid_json, _}} = Protocol.decode(~s({"invalid))
    end

    test "returns error for missing jsonrpc field" do
      assert {:error, {:invalid_jsonrpc, _}} = Protocol.decode(~s({"id":1,"result":{}}))
    end

    test "returns error for wrong jsonrpc version" do
      assert {:error, {:invalid_jsonrpc, _}} = Protocol.decode(~s({"jsonrpc":"1.0"}))
    end
  end

  describe "frame/1" do
    test "frames a message with Content-Length header" do
      message = %{"jsonrpc" => "2.0", "id" => 1, "method" => "test"}
      framed = Protocol.frame(message)

      # Should contain Content-Length header
      assert String.starts_with?(framed, "Content-Length:")
      assert String.contains?(framed, "\r\n\r\n")

      # Should contain the JSON body after the double newline
      [header, body] = String.split(framed, "\r\n\r\n", parts: 2)
      assert {:ok, _} = Jason.decode(body)
    end

    test "correct Content-Length matches body bytes" do
      message = %{"jsonrpc" => "2.0", "id" => 1, "method" => "test"}
      body = Jason.encode!(message)

      framed = Protocol.frame(message)

      # Extract content length from header
      [header | _] = String.split(framed, "\r\n\r\n")
      [_, length_str] = String.split(header, "Content-Length: ")
      {length, _} = Integer.parse(length_str)

      assert length == byte_size(body)
    end
  end

  describe "parse_framed/1" do
    test "parses single framed message" do
      message = %{"jsonrpc" => "2.0", "id" => 1, "result" => %{"ok" => true}}
      framed = Protocol.frame(message)

      assert {[decoded], ""} = Protocol.parse_framed(framed)
      assert decoded["id"] == 1
      assert decoded["result"]["ok"] == true
    end

    test "parses multiple framed messages" do
      msg1 = Protocol.frame(%{"jsonrpc" => "2.0", "id" => 1, "result" => %{"a" => 1}})
      msg2 = Protocol.frame(%{"jsonrpc" => "2.0", "id" => 2, "result" => %{"b" => 2}})

      combined = msg1 <> msg2

      assert {[decoded1, decoded2], ""} = Protocol.parse_framed(combined)
      assert decoded1["id"] == 1
      assert decoded2["id"] == 2
    end

    test "returns incomplete data as rest buffer" do
      # Incomplete - missing part of body
      incomplete = "Content-Length: 50\r\n\r\n{\"jsonrpc\":\"2.0\""

      assert {[], ^incomplete} = Protocol.parse_framed(incomplete)
    end

    test "parses complete messages and keeps incomplete rest" do
      complete = Protocol.frame(%{"jsonrpc" => "2.0", "id" => 1, "result" => %{}})
      incomplete = "Content-Length: 50\r\n\r\n{\"jsonrpc\":\"2.0\""

      buffer = complete <> incomplete

      assert {[decoded], rest} = Protocol.parse_framed(buffer)
      assert decoded["id"] == 1
      assert rest == incomplete
    end
  end

  describe "notification?/1" do
    test "returns true for notification (no id)" do
      assert Protocol.notification?(%{"jsonrpc" => "2.0", "method" => "test"})
    end

    test "returns false for request (has id)" do
      refute Protocol.notification?(%{"jsonrpc" => "2.0", "id" => 1, "method" => "test"})
    end
  end

  describe "request?/1" do
    test "returns true for request (has method and id)" do
      assert Protocol.request?(%{"jsonrpc" => "2.0", "id" => 1, "method" => "test"})
    end

    test "returns false for notification (no id)" do
      refute Protocol.request?(%{"jsonrpc" => "2.0", "method" => "test"})
    end

    test "returns false for response (no method)" do
      refute Protocol.request?(%{"jsonrpc" => "2.0", "id" => 1, "result" => %{}})
    end
  end

  describe "response?/1" do
    test "returns true for success response" do
      assert Protocol.response?(%{"jsonrpc" => "2.0", "id" => 1, "result" => %{}})
    end

    test "returns true for error response" do
      assert Protocol.response?(%{"jsonrpc" => "2.0", "id" => 1, "error" => %{}})
    end

    test "returns false for request" do
      refute Protocol.response?(%{"jsonrpc" => "2.0", "id" => 1, "method" => "test"})
    end
  end
end
