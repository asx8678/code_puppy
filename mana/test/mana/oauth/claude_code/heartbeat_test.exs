defmodule Mana.OAuth.ClaudeCode.HeartbeatTest do
  @moduledoc """
  Tests for Mana.OAuth.ClaudeCode.Heartbeat module.

  These tests verify the periodic token refresh functionality.
  Each test uses a uniquely-named GenServer to avoid state conflicts.
  """

  use ExUnit.Case, async: false

  import Mana.TestHelpers
  import Mock

  alias Mana.OAuth.ClaudeCode.Heartbeat
  alias Mana.OAuth.TokenStore

  setup do
    # Use a temporary directory for tests
    temp_dir =
      Path.join(System.tmp_dir!(), "mana_heartbeat_test_#{:erlang.unique_integer([:positive])}")

    # Override the default tokens directory for testing
    original_tokens_dir = Application.get_env(:mana, :tokens_dir)
    Application.put_env(:mana, :tokens_dir, temp_dir)

    # Create the directory
    File.mkdir_p!(temp_dir)

    # Generate a unique name for this test's GenServer
    test_name = String.to_atom("heartbeat_test_#{:erlang.unique_integer([:positive])}")

    on_exit(fn ->
      # Cleanup
      File.rm_rf!(temp_dir)

      if original_tokens_dir do
        Application.put_env(:mana, :tokens_dir, original_tokens_dir)
      else
        Application.delete_env(:mana, :tokens_dir)
      end
    end)

    {:ok, temp_dir: temp_dir, test_name: test_name}
  end

  describe "start_link/1" do
    test "starts the GenServer", %{test_name: test_name} do
      assert {:ok, pid} = Heartbeat.start_link(name: test_name)
      assert Process.alive?(pid)
      GenServer.stop(pid)
    end

    test "defaults to module name registration" do
      # Clean up any existing process first
      case Process.whereis(Heartbeat) do
        nil ->
          :ok

        pid ->
          try do
            GenServer.stop(pid)
          catch
            _, _ -> :ok
          end
      end

      assert {:ok, pid} = Heartbeat.start_link([])
      assert Process.whereis(Heartbeat) == pid
      GenServer.stop(pid)
    end
  end

  describe "start_heartbeat/0 and stop_heartbeat/0" do
    test "starts and stops heartbeat", %{test_name: test_name} do
      {:ok, pid} = Heartbeat.start_link(name: test_name)

      # Use call to get fresh state
      refute Heartbeat.active?(test_name)

      Heartbeat.start_heartbeat(test_name)
      assert Heartbeat.active?(test_name)

      Heartbeat.stop_heartbeat(test_name)
      refute Heartbeat.active?(test_name)

      GenServer.stop(pid)
    end
  end

  describe "active?/0" do
    test "returns false when not started", %{test_name: test_name} do
      {:ok, pid} = Heartbeat.start_link(name: test_name)

      refute Heartbeat.active?(test_name)
      GenServer.stop(pid)
    end

    test "returns true when started", %{test_name: test_name} do
      {:ok, pid} = Heartbeat.start_link(name: test_name)

      Heartbeat.start_heartbeat(test_name)
      assert Heartbeat.active?(test_name)
      GenServer.stop(pid)
    end
  end

  describe "refresh_now/0" do
    test "triggers immediate refresh check", %{temp_dir: _, test_name: test_name} do
      # Save an expired token
      past_time = System.os_time(:second) - 100

      tokens = %{
        "access_token" => "old_token",
        "refresh_token" => "refresh_token",
        "expires_at" => past_time
      }

      TokenStore.save("claude_code", tokens)

      {:ok, pid} = Heartbeat.start_link(name: test_name)

      with_mock Req,
        post: fn _url, _opts ->
          {:ok,
           %{
             status: 200,
             body: %{
               "access_token" => "new_token",
               "expires_in" => 3600
             }
           }}
        end do
        Heartbeat.start_heartbeat(test_name)

        # Trigger immediate refresh
        Heartbeat.refresh_now(test_name)

        # Wait for the GenServer to process and verify token was refreshed
        assert_eventually(
          fn ->
            case TokenStore.load("claude_code") do
              {:ok, saved} -> saved["access_token"] == "new_token"
              _ -> false
            end
          end,
          timeout: 1000
        )

        GenServer.stop(pid)
      end
    end
  end

  describe "periodic refresh" do
    test "does nothing when token is not expired", %{temp_dir: _, test_name: test_name} do
      # Save a valid token
      future_time = System.os_time(:second) + 3600

      tokens = %{
        "access_token" => "valid_token",
        "refresh_token" => "refresh_token",
        "expires_at" => future_time
      }

      TokenStore.save("claude_code", tokens)

      {:ok, pid} = Heartbeat.start_link(name: test_name)

      # Start the heartbeat
      Heartbeat.start_heartbeat(test_name)

      # Trigger refresh check manually
      Heartbeat.refresh_now(test_name)

      # Token should remain unchanged (no Req.post calls expected)
      assert_eventually(
        fn ->
          {:ok, saved_tokens} = TokenStore.load("claude_code")
          saved_tokens["access_token"] == "valid_token"
        end,
        timeout: 200
      )

      GenServer.stop(pid)
    end

    test "handles missing tokens gracefully", %{test_name: test_name} do
      # Ensure no tokens exist
      TokenStore.delete("claude_code")

      {:ok, pid} = Heartbeat.start_link(name: test_name)

      # Start the heartbeat - should not crash
      Heartbeat.start_heartbeat(test_name)

      # Trigger refresh manually
      Heartbeat.refresh_now(test_name)

      # Should still be active
      assert_eventually(
        fn -> Heartbeat.active?(test_name) end,
        timeout: 200
      )

      GenServer.stop(pid)
    end
  end

  describe "error handling" do
    test "handles refresh failure gracefully", %{temp_dir: _, test_name: test_name} do
      # Save an expired token
      past_time = System.os_time(:second) - 100

      tokens = %{
        "access_token" => "old_token",
        "refresh_token" => "invalid_refresh",
        "expires_at" => past_time
      }

      TokenStore.save("claude_code", tokens)

      {:ok, pid} = Heartbeat.start_link(name: test_name)

      with_mock Req,
        post: fn _url, _opts ->
          {:ok, %{status: 401, body: %{"error" => "invalid_grant"}}}
        end do
        # Start the heartbeat - should not crash on refresh failure
        Heartbeat.start_heartbeat(test_name)

        # Trigger the refresh attempt
        Heartbeat.refresh_now(test_name)

        # Should still be active despite refresh failure
        assert_eventually(
          fn -> Heartbeat.active?(test_name) end,
          timeout: 200
        )

        GenServer.stop(pid)
      end
    end

    test "handles network errors gracefully", %{temp_dir: _, test_name: test_name} do
      # Save an expired token
      past_time = System.os_time(:second) - 100

      tokens = %{
        "access_token" => "old_token",
        "refresh_token" => "refresh_token",
        "expires_at" => past_time
      }

      TokenStore.save("claude_code", tokens)

      {:ok, pid} = Heartbeat.start_link(name: test_name)

      with_mock Req,
        post: fn _url, _opts ->
          {:error, :timeout}
        end do
        # Start the heartbeat - should not crash on network error
        Heartbeat.start_heartbeat(test_name)

        # Trigger the refresh attempt
        Heartbeat.refresh_now(test_name)

        # Should still be active despite network error
        assert_eventually(
          fn -> Heartbeat.active?(test_name) end,
          timeout: 200
        )

        GenServer.stop(pid)
      end
    end
  end

  describe "idempotency" do
    test "starting heartbeat multiple times cancels previous timer", %{test_name: test_name} do
      {:ok, pid} = Heartbeat.start_link(name: test_name)

      Heartbeat.start_heartbeat(test_name)
      first_active = Heartbeat.active?(test_name)

      # Start again - should not cause issues
      Heartbeat.start_heartbeat(test_name)
      second_active = Heartbeat.active?(test_name)

      assert first_active == true
      assert second_active == true

      GenServer.stop(pid)
    end

    test "stopping heartbeat multiple times does not cause errors", %{test_name: test_name} do
      {:ok, pid} = Heartbeat.start_link(name: test_name)

      Heartbeat.start_heartbeat(test_name)
      assert Heartbeat.active?(test_name)

      Heartbeat.stop_heartbeat(test_name)
      refute Heartbeat.active?(test_name)

      # Stop again - should not cause errors
      Heartbeat.stop_heartbeat(test_name)
      refute Heartbeat.active?(test_name)

      GenServer.stop(pid)
    end
  end
end
