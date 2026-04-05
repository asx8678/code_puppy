defmodule Mana.Tools.Browser.ProtocolTest do
  @moduledoc """
  Tests for Mana.Tools.Browser.Protocol module.

  Covers JSON-RPC command encoding, response decoding, classification,
  and command builder helpers.
  """

  use ExUnit.Case, async: true

  alias Mana.Tools.Browser.Protocol

  # ---------------------------------------------------------------------------
  # Encoding
  # ---------------------------------------------------------------------------

  describe "encode_command/3" do
    test "encodes a command with default id" do
      assert {:ok, json} = Protocol.encode_command("navigate", %{"url" => "https://example.com"})
      assert json =~ ~s("id":1)
      assert json =~ ~s("command":"navigate")
      assert json =~ ~s("url":"https://example.com")
      assert String.ends_with?(json, "\n")
    end

    test "encodes a command with custom id" do
      assert {:ok, json} = Protocol.encode_command("click", %{"selector" => "#btn"}, id: 42)
      assert json =~ ~s("id":42)
      assert json =~ ~s("command":"click")
      assert json =~ ~s("selector":"#btn")
    end

    test "produces valid JSON" do
      assert {:ok, json} = Protocol.encode_command("screenshot", %{"full_page" => true})
      assert {:ok, decoded} = Jason.decode(String.trim(json))
      assert decoded["id"] == 1
      assert decoded["command"] == "screenshot"
      assert decoded["params"]["full_page"] == true
    end

    test "encodes empty params" do
      assert {:ok, json} = Protocol.encode_command("close", %{})
      assert json =~ ~s("params":{})
    end
  end

  describe "encode_command!/3" do
    test "returns JSON string on success" do
      json = Protocol.encode_command!("navigate", %{"url" => "https://example.com"}, id: 1)
      assert is_binary(json)
      assert json =~ ~s("command":"navigate")
    end
  end

  # ---------------------------------------------------------------------------
  # Decoding
  # ---------------------------------------------------------------------------

  describe "decode_response/1" do
    test "decodes a success response" do
      json = ~s({"id":1,"success":true,"result":{"url":"https://example.com"}})

      assert {:ok, decoded} = Protocol.decode_response(json)
      assert decoded["id"] == 1
      assert decoded["success"] == true
      assert decoded["result"]["url"] == "https://example.com"
    end

    test "decodes an error response" do
      json = ~s({"id":2,"success":false,"error":"timeout"})

      assert {:ok, decoded} = Protocol.decode_response(json)
      assert decoded["id"] == 2
      assert decoded["success"] == false
      assert decoded["error"] == "timeout"
    end

    test "handles trailing newline" do
      json = ~s({"id":1,"success":true,"result":{}}) <> "\n"

      assert {:ok, decoded} = Protocol.decode_response(json)
      assert decoded["success"] == true
    end

    test "returns error for invalid JSON" do
      assert {:error, _reason} = Protocol.decode_response("not json at all")
    end

    test "returns error for empty string" do
      assert {:error, _} = Protocol.decode_response("")
    end
  end

  describe "decode_response!/1" do
    test "returns result map on success" do
      json = ~s({"id":1,"success":true,"result":{"url":"https://example.com"}})

      assert %{"url" => "https://example.com"} = Protocol.decode_response!(json)
    end

    test "returns empty map on success without result" do
      json = ~s({"id":1,"success":true})

      assert %{} = Protocol.decode_response!(json)
    end

    test "raises on error response" do
      json = ~s({"id":1,"success":false,"error":"timeout"})

      assert_raise RuntimeError, ~r/Browser command failed/, fn ->
        Protocol.decode_response!(json)
      end
    end

    test "raises on invalid JSON" do
      assert_raise RuntimeError, ~r/Failed to decode/, fn ->
        Protocol.decode_response!("not json")
      end
    end
  end

  # ---------------------------------------------------------------------------
  # Classification
  # ---------------------------------------------------------------------------

  describe "classify/1" do
    test "classifies success response" do
      response = %{"success" => true, "result" => %{"url" => "https://example.com"}}
      assert {:ok, %{"url" => "https://example.com"}} = Protocol.classify(response)
    end

    test "classifies success response without result" do
      response = %{"success" => true}
      assert {:ok, %{}} = Protocol.classify(response)
    end

    test "classifies error response" do
      response = %{"success" => false, "error" => "not initialized"}
      assert {:error, "not initialized"} = Protocol.classify(response)
    end

    test "classifies unexpected response" do
      response = %{"unexpected" => "data"}
      assert {:error, msg} = Protocol.classify(response)
      assert msg =~ "unexpected response"
    end
  end

  # ---------------------------------------------------------------------------
  # Command Builder Helpers
  # ---------------------------------------------------------------------------

  describe "init_command/1" do
    test "returns defaults" do
      params = Protocol.init_command()
      assert params["headless"] == true
      assert params["browser_type"] == "chromium"
      assert params["homepage"] == "https://www.google.com"
    end

    test "accepts custom options" do
      params = Protocol.init_command(headless: false, browser_type: "firefox", homepage: "https://example.com")
      assert params["headless"] == false
      assert params["browser_type"] == "firefox"
      assert params["homepage"] == "https://example.com"
    end
  end

  describe "navigate_command/2" do
    test "returns navigate params with defaults" do
      params = Protocol.navigate_command("https://example.com")
      assert params["url"] == "https://example.com"
      assert params["wait_until"] == "domcontentloaded"
      assert params["timeout"] == 30_000
    end

    test "accepts custom options" do
      params = Protocol.navigate_command("https://example.com", wait_until: "load", timeout: 60_000)
      assert params["wait_until"] == "load"
      assert params["timeout"] == 60_000
    end
  end

  describe "click_command/2" do
    test "returns click params with defaults" do
      params = Protocol.click_command("#submit")
      assert params["selector"] == "#submit"
      assert params["timeout"] == 10_000
      assert params["force"] == false
      assert params["button"] == "left"
    end
  end

  describe "type_command/3" do
    test "returns type params with defaults" do
      params = Protocol.type_command("#input", "hello world")
      assert params["selector"] == "#input"
      assert params["text"] == "hello world"
      assert params["clear_first"] == true
    end
  end

  describe "screenshot_command/1" do
    test "returns screenshot params with defaults" do
      params = Protocol.screenshot_command()
      assert params["full_page"] == false
      refute Map.has_key?(params, "selector")
    end

    test "includes selector when provided" do
      params = Protocol.screenshot_command(selector: "#content")
      assert params["selector"] == "#content"
    end
  end

  describe "find_text_command/2" do
    test "returns find params with defaults" do
      params = Protocol.find_text_command("Login")
      assert params["text"] == "Login"
      assert params["exact"] == false
      assert params["timeout"] == 10_000
    end
  end

  describe "scroll_command/1" do
    test "returns scroll params with defaults" do
      params = Protocol.scroll_command()
      assert params["direction"] == "down"
      assert params["amount"] == 3
      refute Map.has_key?(params, "selector")
    end

    test "excludes nil selector" do
      params = Protocol.scroll_command(selector: nil)
      refute Map.has_key?(params, "selector")
    end

    test "includes selector when provided" do
      params = Protocol.scroll_command(selector: "#content")
      assert params["selector"] == "#content"
    end
  end
end
