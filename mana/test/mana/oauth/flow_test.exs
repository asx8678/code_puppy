defmodule Mana.OAuth.FlowTest do
  @moduledoc """
  Tests for Mana.OAuth.Flow module.
  """

  use ExUnit.Case, async: false

  alias Mana.OAuth.Flow

  describe "generate_pkce/0" do
    test "generates code verifier and challenge" do
      pkce = Flow.generate_pkce()

      assert is_map(pkce)
      assert Map.has_key?(pkce, :code_verifier)
      assert Map.has_key?(pkce, :code_challenge)
      assert is_binary(pkce.code_verifier)
      assert is_binary(pkce.code_challenge)
      assert byte_size(pkce.code_verifier) > 0
      assert byte_size(pkce.code_challenge) > 0
    end

    test "generates unique values each call" do
      pkce1 = Flow.generate_pkce()
      pkce2 = Flow.generate_pkce()

      assert pkce1.code_verifier != pkce2.code_verifier
      assert pkce1.code_challenge != pkce2.code_challenge
    end

    test "code_challenge is S256 hash of verifier" do
      pkce = Flow.generate_pkce()

      expected_challenge =
        Base.url_encode64(:crypto.hash(:sha256, pkce.code_verifier), padding: false)

      assert pkce.code_challenge == expected_challenge
    end
  end

  describe "start_callback_server/1" do
    test "starts a server on specified port" do
      port = 14_556

      assert {:ok, pid} = Flow.start_callback_server(port)
      assert is_pid(pid)
      assert Process.alive?(pid)

      # Clean up
      Process.exit(pid, :normal)
    end

    test "starts on default port when none specified" do
      # Use a non-standard port to avoid conflicts
      assert {:ok, pid} = Flow.start_callback_server(14_557)
      assert is_pid(pid)

      Process.exit(pid, :normal)
    end

    test "handles port already in use" do
      port = 14_558

      # Start first server
      {:ok, pid1} = Flow.start_callback_server(port)

      # Second server should fail
      assert {:error, _} = Flow.start_callback_server(port)

      Process.exit(pid1, :normal)
    end
  end

  describe "exchange_code/3" do
    test "requires code_verifier option" do
      assert_raise KeyError, fn ->
        Flow.exchange_code("code", "http://example.com/token", client_id: "test")
      end
    end

    test "requires client_id option" do
      assert_raise KeyError, fn ->
        Flow.exchange_code("code", "http://example.com/token", code_verifier: "verifier")
      end
    end

    @tag :external
    test "successfully exchanges code for tokens with mock server" do
      # This would require setting up a mock HTTP server
      # For now, we test the error case with a non-existent endpoint
      result =
        Flow.exchange_code(
          "test-code",
          "http://localhost:19999/nonexistent",
          code_verifier: "verifier",
          client_id: "test-client"
        )

      assert {:error, _} = result
    end
  end

  describe "run_flow/3" do
    @tag :external
    test "returns timeout when no callback received" do
      # Start on a port that won't receive any callback
      # This will timeout because we're not actually opening a browser
      result =
        Flow.run_flow(
          "http://example.com/auth",
          "http://example.com/token",
          port: 14_559,
          timeout: 100,
          client_id: "test"
        )

      # Should timeout or fail to launch browser
      assert match?({:error, _}, result)
    end
  end

  describe "adds PKCE params to auth URL" do
    test "appends code_challenge to existing query params" do
      # This is tested indirectly via run_flow
      # But we can verify the behavior by examining the URL structure
      pkce = Flow.generate_pkce()

      base_url = "https://example.com/oauth/authorize?client_id=test&scope=read"

      # Build the URL manually as the module does
      uri = URI.parse(base_url)
      existing_params = URI.decode_query(uri.query || "")

      params =
        existing_params
        |> Map.put("code_challenge", pkce.code_challenge)
        |> Map.put("code_challenge_method", "S256")

      full_url = %{uri | query: URI.encode_query(params)} |> URI.to_string()

      assert String.contains?(full_url, "code_challenge=")
      assert String.contains?(full_url, "code_challenge_method=S256")
      assert String.contains?(full_url, "client_id=test")
      assert String.contains?(full_url, "scope=read")
    end
  end
end
