defmodule Mana.OAuth.ClaudeCodeTest do
  @moduledoc """
  Tests for Mana.OAuth.ClaudeCode module.

  These tests use mocking to avoid making real API calls.
  """

  use ExUnit.Case, async: false

  import Mock

  alias Mana.OAuth.ClaudeCode
  alias Mana.OAuth.TokenStore

  setup do
    # Use a temporary directory for tests
    temp_dir =
      Path.join(System.tmp_dir!(), "mana_claude_code_test_#{:erlang.unique_integer([:positive])}")

    # Override the default tokens directory for testing
    original_tokens_dir = Application.get_env(:mana, :tokens_dir)
    Application.put_env(:mana, :tokens_dir, temp_dir)

    # Create the directory
    File.mkdir_p!(temp_dir)

    on_exit(fn ->
      # Cleanup
      File.rm_rf!(temp_dir)

      if original_tokens_dir do
        Application.put_env(:mana, :tokens_dir, original_tokens_dir)
      else
        Application.delete_env(:mana, :tokens_dir)
      end
    end)

    {:ok, temp_dir: temp_dir}
  end

  describe "provider_id/0" do
    test "returns 'claude_code'" do
      assert ClaudeCode.provider_id() == "claude_code"
    end
  end

  describe "validate_config/1" do
    test "returns :ok when valid token exists", %{temp_dir: _} do
      # Save valid token
      future_time = System.os_time(:second) + 3600
      tokens = %{"access_token" => "valid_token", "expires_at" => future_time}
      TokenStore.save("claude_code", tokens)

      assert :ok = ClaudeCode.validate_config(%{})
    end

    test "refreshes expired token and returns :ok", %{temp_dir: _} do
      past_time = System.os_time(:second) - 100

      tokens = %{
        "access_token" => "old_token",
        "refresh_token" => "refresh_token",
        "expires_at" => past_time
      }

      TokenStore.save("claude_code", tokens)

      # Mock the token refresh endpoint
      with_mock Req,
        post: fn
          "https://anthropic.com/oauth/token", _opts ->
            {:ok,
             %{
               status: 200,
               body: %{
                 "access_token" => "new_token",
                 "expires_in" => 3600
               }
             }}
        end do
        assert :ok = ClaudeCode.validate_config(%{})
      end
    end

    test "returns error when no tokens exist", %{temp_dir: _} do
      assert {:error, "No Claude Code token — run /oauth claude_code"} =
               ClaudeCode.validate_config(%{})
    end

    test "returns error when token refresh fails", %{temp_dir: _} do
      past_time = System.os_time(:second) - 100

      tokens = %{
        "access_token" => "old_token",
        "refresh_token" => "invalid_refresh",
        "expires_at" => past_time
      }

      TokenStore.save("claude_code", tokens)

      with_mock Req,
        post: fn
          "https://anthropic.com/oauth/token", _opts ->
            {:ok, %{status: 401, body: %{"error" => "invalid_grant"}}}
        end do
        assert {:error, _} = ClaudeCode.validate_config(%{})
      end
    end
  end

  describe "complete/3" do
    test "returns error when no token available", %{temp_dir: _} do
      messages = [%{"role" => "user", "content" => "Hello"}]

      assert {:error, :not_found} = ClaudeCode.complete(messages, "claude-sonnet-4-20250514")
    end

    test "successfully completes request", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      response_body = %{
        "content" => [
          %{
            "type" => "text",
            "text" => "Hello! How can I help you?"
          }
        ],
        "usage" => %{"input_tokens" => 10, "output_tokens" => 20}
      }

      with_mock Req,
        post: fn
          "https://api.anthropic.com/v1/messages", opts ->
            # Verify headers include beta headers
            headers = Keyword.get(opts, :headers, [])
            beta_headers = Enum.filter(headers, fn {k, _} -> k == "anthropic-beta" end)
            assert length(beta_headers) == 3

            {:ok, %{status: 200, body: response_body}}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]
        {:ok, response} = ClaudeCode.complete(messages, "claude-sonnet-4-20250514")

        assert response.content == "Hello! How can I help you?"
        assert response.model == "claude"
        assert response.usage == %{"input_tokens" => 10, "output_tokens" => 20}
      end
    end

    test "handles API error", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      with_mock Req,
        post: fn _url, _opts ->
          {:ok, %{status: 500, body: %{"error" => "Internal Server Error"}}}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]

        assert {:error, "Claude Code API error: 500" <> _} =
                 ClaudeCode.complete(messages, "claude-sonnet-4-20250514")
      end
    end

    test "handles network error", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      with_mock Req,
        post: fn _url, _opts ->
          {:error, :nxdomain}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]

        assert {:error, "Request failed: :nxdomain"} =
                 ClaudeCode.complete(messages, "claude-sonnet-4-20250514")
      end
    end

    test "handles 401 by refreshing and retrying", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "expired_token",
        "refresh_token" => "refresh_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      refreshed_tokens = %{
        "access_token" => "new_token",
        "expires_in" => 3600
      }

      response_body = %{
        "content" => [%{"type" => "text", "text" => "Success after refresh!"}],
        "usage" => %{}
      }

      call_count = :atomics.new(1, signed: false)

      with_mock Req,
        post: fn
          "https://anthropic.com/oauth/token", _opts ->
            {:ok, %{status: 200, body: refreshed_tokens}}

          "https://api.anthropic.com/v1/messages", _opts ->
            count = :atomics.add_get(call_count, 1, 1)

            if count == 1 do
              # First call fails with 401
              {:ok, %{status: 401, body: %{}}}
            else
              # Second call succeeds
              {:ok, %{status: 200, body: response_body}}
            end
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]
        {:ok, response} = ClaudeCode.complete(messages, "claude-sonnet-4-20250514")

        assert response.content == "Success after refresh!"
      end
    end
  end

  describe "stream/3" do
    test "returns error stream when no token available", %{temp_dir: _} do
      messages = [%{"role" => "user", "content" => "Hello"}]
      stream = ClaudeCode.stream(messages, "claude-sonnet-4-20250514")

      events = Enum.to_list(stream)
      assert length(events) == 1
      assert {:error, :not_found} = hd(events)
    end

    test "handles streaming response", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      with_mock Req,
        new: fn _opts ->
          %{}
        end,
        request: fn _req ->
          # Return mocked response body as list (simulating streaming chunks)
          {:ok,
           %{
             status: 200,
             body: [
               ~s(data: {"type": "message_start", "message": {"id": "msg_123"}}) <> "\n\n",
               ~s(data: {"type": "content_block_start", "content_block": {"type": "text"}}) <> "\n\n",
               ~s(data: {"type": "content_block_delta", "delta": {"text": "Hello"}}) <> "\n\n",
               ~s(data: {"type": "content_block_delta", "delta": {"text": " there!"}}) <> "\n\n",
               ~s(data: {"type": "content_block_stop"}) <> "\n\n",
               ~s(data: {"type": "message_stop"}) <> "\n\n",
               ~s(data: [DONE]) <> "\n\n"
             ]
           }}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]
        stream = ClaudeCode.stream(messages, "claude-sonnet-4-20250514")
        events = Enum.to_list(stream)

        assert {:part_start, :message} in events
        assert {:part_start, :content} in events
        assert {:part_delta, :content, "Hello"} in events
        assert {:part_delta, :content, " there!"} in events
        assert {:part_end, :done} in events
      end
    end

    test "handles stream API error", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      with_mock Req,
        new: fn _opts -> %{} end,
        request: fn _req ->
          {:ok, %{status: 500, body: "Server Error"}}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]
        stream = ClaudeCode.stream(messages, "claude-sonnet-4-20250514")
        events = Enum.to_list(stream)

        assert {:error, "HTTP 500"} in events
      end
    end
  end

  describe "inject_cache_control/1" do
    test "adds cache_control to system messages" do
      messages = [
        %{"role" => "system", "content" => "You are helpful"},
        %{"role" => "user", "content" => "Hello"}
      ]

      result = ClaudeCode.inject_cache_control(messages)

      assert hd(result)["cache_control"] == %{"type" => "ephemeral"}
      assert Enum.at(result, 1)["cache_control"] == nil
    end

    test "handles atom keys for role" do
      messages = [
        %{role: :system, content: "You are helpful"},
        %{role: :user, content: "Hello"}
      ]

      result = ClaudeCode.inject_cache_control(messages)

      assert hd(result)["cache_control"] == %{"type" => "ephemeral"}
    end

    test "handles empty messages" do
      assert ClaudeCode.inject_cache_control([]) == []
    end

    test "handles non-list input gracefully" do
      assert ClaudeCode.inject_cache_control(nil) == nil
      assert ClaudeCode.inject_cache_control("string") == "string"
    end
  end

  describe "start_link/1" do
    test "returns :ignore" do
      assert :ignore = ClaudeCode.start_link([])
    end
  end

  describe "start_oauth/1" do
    test "requires mocking for full testing" do
      # This test verifies that start_oauth function exists and has correct signature
      # Full testing would require mocking the Flow module and browser launch
      assert function_exported?(ClaudeCode, :start_oauth, 1)
    end
  end

  describe "message conversion" do
    test "converts atom-key messages to string keys", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      with_mock Req,
        post: fn _url, opts ->
          body = Keyword.get(opts, :json)
          messages = Map.get(body, "messages")

          # Verify cache_control was injected for system messages
          system_msg = Enum.find(messages, fn m -> m["role"] == "system" end)
          assert system_msg["cache_control"] == %{"type" => "ephemeral"}

          # Verify messages have string keys
          assert Map.has_key?(hd(messages), "role")
          assert Map.has_key?(hd(messages), "content")

          {:ok,
           %{
             status: 200,
             body: %{
               "content" => [%{"type" => "text", "text" => "Response"}],
               "usage" => %{}
             }
           }}
        end do
        messages = [
          %{role: :system, content: "You are helpful"},
          %{role: :user, content: "Hello"}
        ]

        {:ok, _response} = ClaudeCode.complete(messages, "claude-sonnet-4-20250514")
      end
    end
  end

  describe "refresh_token/1" do
    test "successfully refreshes token", %{temp_dir: _} do
      tokens = %{"refresh_token" => "valid_refresh_token"}

      with_mock Req,
        post: fn
          "https://anthropic.com/oauth/token", opts ->
            body = Keyword.get(opts, :json)
            assert body[:grant_type] == "refresh_token"
            assert body[:refresh_token] == "valid_refresh_token"

            {:ok,
             %{
               status: 200,
               body: %{
                 "access_token" => "new_access_token",
                 "expires_in" => 3600
               }
             }}
        end do
        assert {:ok, "new_access_token"} = ClaudeCode.refresh_token(tokens)

        # Verify the new token was saved
        {:ok, saved_tokens} = TokenStore.load("claude_code")
        assert saved_tokens["access_token"] == "new_access_token"
        assert is_integer(saved_tokens["expires_at"])
      end
    end

    test "returns error when no refresh token" do
      tokens = %{"access_token" => "some_token"}

      assert {:error, "No refresh token"} = ClaudeCode.refresh_token(tokens)
    end

    test "handles refresh failure", %{temp_dir: _} do
      tokens = %{"refresh_token" => "invalid_refresh"}

      with_mock Req,
        post: fn _url, _opts ->
          {:ok, %{status: 401, body: %{"error" => "invalid_grant"}}}
        end do
        assert {:error, "Refresh failed: HTTP 401" <> _} =
                 ClaudeCode.refresh_token(tokens)
      end
    end
  end
end
