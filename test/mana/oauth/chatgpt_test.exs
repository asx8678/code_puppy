defmodule Mana.OAuth.ChatGPTTest do
  @moduledoc """
  Tests for Mana.OAuth.ChatGPT module.

  These tests use mocking to avoid making real API calls.
  """

  use ExUnit.Case, async: false

  import Mock

  alias Mana.OAuth.ChatGPT
  alias Mana.OAuth.TokenStore

  setup do
    # Use a temporary directory for tests
    temp_dir =
      Path.join(System.tmp_dir!(), "mana_chatgpt_test_#{:erlang.unique_integer([:positive])}")

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
    test "returns 'chatgpt'" do
      assert ChatGPT.provider_id() == "chatgpt"
    end
  end

  describe "validate_config/1" do
    test "returns :ok when valid token exists", %{temp_dir: _} do
      # Save valid token
      future_time = System.os_time(:second) + 3600
      tokens = %{"access_token" => "valid_token", "expires_at" => future_time}
      TokenStore.save("chatgpt", tokens)

      assert :ok = ChatGPT.validate_config(%{})
    end

    test "refreshes expired token and returns :ok", %{temp_dir: _} do
      past_time = System.os_time(:second) - 100

      tokens = %{
        "access_token" => "old_token",
        "refresh_token" => "refresh_token",
        "expires_at" => past_time
      }

      TokenStore.save("chatgpt", tokens)

      # Mock the token refresh endpoint
      with_mock Req,
        post: fn
          "https://auth.openai.com/oauth/token", _opts ->
            {:ok,
             %{
               status: 200,
               body: %{
                 "access_token" => "new_token",
                 "expires_in" => 3600
               }
             }}
        end do
        assert :ok = ChatGPT.validate_config(%{})
      end
    end

    test "returns error when no tokens exist", %{temp_dir: _} do
      assert {:error, "No ChatGPT token — run /oauth chatgpt"} = ChatGPT.validate_config(%{})
    end

    test "returns error when token refresh fails", %{temp_dir: _} do
      past_time = System.os_time(:second) - 100

      tokens = %{
        "access_token" => "old_token",
        "refresh_token" => "invalid_refresh",
        "expires_at" => past_time
      }

      TokenStore.save("chatgpt", tokens)

      with_mock Req,
        post: fn
          "https://auth.openai.com/oauth/token", _opts ->
            {:ok, %{status: 401, body: %{"error" => "invalid_grant"}}}
        end do
        assert {:error, _} = ChatGPT.validate_config(%{})
      end
    end
  end

  describe "complete/3" do
    test "returns error when no token available", %{temp_dir: _} do
      messages = [%{"role" => "user", "content" => "Hello"}]

      assert {:error, :not_found} = ChatGPT.complete(messages, "gpt-4o")
    end

    test "successfully completes request", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token_" <> String.duplicate("x", 100),
        "expires_at" => future_time
      }

      TokenStore.save("chatgpt", tokens)

      response_body = %{
        "output" => [
          %{
            "type" => "message",
            "content" => [
              %{
                "type" => "output_text",
                "text" => "Hello! How can I help you?"
              }
            ]
          }
        ],
        "usage" => %{"prompt_tokens" => 10, "completion_tokens" => 20}
      }

      with_mock Req,
        new: fn _opts ->
          # Return a simple struct-like map that matches Req.Request
          %{__struct__: Req.Request}
        end,
        request: fn _req ->
          {:ok, %{status: 200, body: response_body}}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]
        {:ok, response} = ChatGPT.complete(messages, "gpt-4o")

        assert response.content == "Hello! How can I help you?"
        assert response.model == "gpt-4o"
        assert response.usage == %{"prompt_tokens" => 10, "completion_tokens" => 20}
      end
    end

    test "handles API error", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("chatgpt", tokens)

      with_mock Req,
        new: fn _opts -> %{} end,
        request: fn _req ->
          {:ok, %{status: 500, body: %{"error" => "Internal Server Error"}}}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]

        assert {:error, "ChatGPT API error: 500" <> _} =
                 ChatGPT.complete(messages, "gpt-4o")
      end
    end

    test "handles network error", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token",
        "expires_at" => future_time
      }

      TokenStore.save("chatgpt", tokens)

      with_mock Req,
        new: fn _opts -> %{} end,
        request: fn _req ->
          {:error, :nxdomain}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]

        assert {:error, "Request failed: :nxdomain"} =
                 ChatGPT.complete(messages, "gpt-4o")
      end
    end

    test "handles 401 by refreshing and retrying", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "expired_token",
        "refresh_token" => "refresh_token",
        "expires_at" => future_time
      }

      TokenStore.save("chatgpt", tokens)

      refreshed_tokens = %{
        "access_token" => "new_token" <> String.duplicate("x", 100),
        "expires_in" => 3600
      }

      response_body = %{
        "output" => [
          %{
            "type" => "message",
            "content" => [
              %{
                "type" => "output_text",
                "text" => "Success after refresh!"
              }
            ]
          }
        ],
        "usage" => %{}
      }

      call_count = :atomics.new(1, signed: false)

      with_mock Req,
        post: fn
          "https://auth.openai.com/oauth/token", _opts ->
            {:ok, %{status: 200, body: refreshed_tokens}}
        end,
        new: fn _opts -> %{} end,
        request: fn _req ->
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
        {:ok, response} = ChatGPT.complete(messages, "gpt-4o")

        assert response.content == "Success after refresh!"
      end
    end
  end

  describe "stream/3" do
    test "returns error stream when no token available", %{temp_dir: _} do
      messages = [%{"role" => "user", "content" => "Hello"}]
      stream = ChatGPT.stream(messages, "gpt-4o")

      events = Enum.to_list(stream)
      assert length(events) == 1
      assert {:error, :not_found} = hd(events)
    end

    test "handles streaming response", %{temp_dir: _} do
      future_time = System.os_time(:second) + 3600

      # Create a valid JWT-like token with proper structure
      token_payload =
        Base.url_encode64(
          Jason.encode!(%{
            "https://api.openai.com/account_id" => "acc_123"
          }),
          padding: false
        )

      tokens = %{
        "access_token" => "eyJhbGciOiJIUzI1NiJ9." <> token_payload <> ".signature",
        "expires_at" => future_time
      }

      TokenStore.save("chatgpt", tokens)

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
               ~s(data: {"type": "response.created"}) <> "\n\n",
               ~s(data: {"type": "response.output_item.added", "item": {"type": "message"}}) <> "\n\n",
               ~s(data: {"type": "response.output_text.delta", "delta": {"text": "Hello"}}) <> "\n\n",
               ~s(data: {"type": "response.output_text.delta", "delta": {"text": " there!"}}) <> "\n\n",
               ~s(data: {"type": "response.completed"}) <> "\n\n",
               ~s(data: [DONE]) <> "\n\n"
             ]
           }}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]
        stream = ChatGPT.stream(messages, "gpt-4o")
        events = Enum.to_list(stream)

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

      TokenStore.save("chatgpt", tokens)

      with_mock Req,
        new: fn _opts -> %{} end,
        request: fn _req ->
          {:ok, %{status: 500, body: "Server Error"}}
        end do
        messages = [%{"role" => "user", "content" => "Hello"}]
        stream = ChatGPT.stream(messages, "gpt-4o")
        events = Enum.to_list(stream)

        assert {:error, "HTTP 500"} in events
      end
    end
  end

  describe "start_link/1" do
    test "returns :ignore" do
      assert :ignore = ChatGPT.start_link([])
    end
  end

  describe "start_oauth/1" do
    @tag :external
    test "requires mocking for full testing" do
      # This test verifies that start_oauth function exists and has correct signature
      # Full testing would require mocking the Flow module and browser launch
      assert function_exported?(ChatGPT, :start_oauth, 1)
    end
  end

  describe "message conversion" do
    test "converts atom-key messages to string keys" do
      # This is tested indirectly via the complete/stream functions
      # but we verify the conversion logic works
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "test_token_" <> String.duplicate("x", 100),
        "expires_at" => future_time
      }

      TokenStore.save("chatgpt", tokens)

      with_mock Req,
        new: fn opts ->
          # Verify that the messages were converted to string keys
          body = Keyword.get(opts, :json)
          messages = Map.get(body, "messages")

          if is_list(messages) do
            case messages do
              [] ->
                :ok

              [first | _] ->
                # Keys should be strings
                assert Map.has_key?(first, "role")
                assert Map.has_key?(first, "content")
            end
          end

          %{}
        end,
        request: fn _req ->
          {:ok,
           %{
             status: 200,
             body: %{
               "output" => [
                 %{
                   "type" => "message",
                   "content" => [%{"type" => "output_text", "text" => "Response"}]
                 }
               ],
               "usage" => %{}
             }
           }}
        end do
        messages = [%{role: :user, content: "Hello"}]
        {:ok, _response} = ChatGPT.complete(messages, "gpt-4o")
      end
    end
  end
end
