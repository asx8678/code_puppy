defmodule CodePuppyControlWeb.TerminalChannelTest do
  use CodePuppyControlWeb.ChannelCase, async: false

  # Each test uses a session ID that matches the token's verified_session_id
  # so that the authorization check passes.

  describe "join" do
    test "joins terminal channel and receives session_started" do
      socket = connect_socket("term-session")
      {:ok, reply, _socket} = Phoenix.ChannelTest.join(socket, "terminal:term-session", %{})

      assert reply.session_id == "term-session"
      assert reply.cols == 80
      assert reply.rows == 24

      # Should receive session_started push
      assert_push "session_started", %{"session_id" => "term-session"}
    end

    test "joins with custom dimensions" do
      socket = connect_socket("big-term")

      {:ok, reply, _socket} =
        Phoenix.ChannelTest.join(socket, "terminal:big-term", %{"cols" => 120, "rows" => 40})

      assert reply.cols == 120
      assert reply.rows == 40
    end

    test "rejects unauthorized session (token doesn't match)" do
      socket = connect_socket("session-a")

      {:error, %{reason: "unauthorized"}} =
        Phoenix.ChannelTest.join(socket, "terminal:session-b", %{})
    end
  end

  describe "input" do
    test "writes data to PTY session" do
      socket = connect_socket("input-test")
      {:ok, _reply, socket} = Phoenix.ChannelTest.join(socket, "terminal:input-test", %{})

      # Flush the session_started push
      assert_push "session_started", _

      ref = Phoenix.ChannelTest.push(socket, "input", %{"data" => "ls\n"})
      assert_reply ref, :ok, %{}

      # Verify the stub recorded the write
      calls = CodePuppyControl.PtyManager.Stub.get_calls("input-test")
      assert {:write, "ls\n"} in calls
    end

    test "rejects input without data" do
      socket = connect_socket("input-missing")
      {:ok, _reply, socket} = Phoenix.ChannelTest.join(socket, "terminal:input-missing", %{})
      assert_push "session_started", _

      ref = Phoenix.ChannelTest.push(socket, "input", %{})
      assert_reply ref, :error, %{reason: "missing_data"}
    end
  end

  describe "resize" do
    test "resizes PTY session" do
      socket = connect_socket("resize-test")
      {:ok, _reply, socket} = Phoenix.ChannelTest.join(socket, "terminal:resize-test", %{})
      assert_push "session_started", _

      ref = Phoenix.ChannelTest.push(socket, "resize", %{"cols" => 120, "rows" => 40})
      assert_reply ref, :ok, %{cols: 120, rows: 40}

      calls = CodePuppyControl.PtyManager.Stub.get_calls("resize-test")
      assert {:resize, %{cols: 120, rows: 40}} in calls
    end

    test "rejects resize without dimensions" do
      socket = connect_socket("resize-missing")
      {:ok, _reply, socket} = Phoenix.ChannelTest.join(socket, "terminal:resize-missing", %{})
      assert_push "session_started", _

      ref = Phoenix.ChannelTest.push(socket, "resize", %{})
      assert_reply ref, :error, %{reason: "missing_cols_or_rows"}
    end
  end

  describe "ping" do
    test "replies with pong" do
      socket = connect_socket("ping-test")
      {:ok, _reply, socket} = Phoenix.ChannelTest.join(socket, "terminal:ping-test", %{})
      assert_push "session_started", _

      ref = Phoenix.ChannelTest.push(socket, "ping", %{"client_time" => "2026-01-01T00:00:00Z"})
      assert_reply ref, :ok, %{"pong" => _, "client_time" => "2026-01-01T00:00:00Z"}
    end
  end

  describe "PTY output" do
    test "receives PTY output as base64-encoded output message" do
      socket = connect_socket("output-test")
      {:ok, _reply, _socket} = Phoenix.ChannelTest.join(socket, "terminal:output-test", %{})
      assert_push "session_started", _

      # Simulate PTY output via the stub
      CodePuppyControl.PtyManager.Stub.simulate_output("output-test", "Hello PTY")

      # Channel should push the output as base64
      assert_push "output", %{"data" => encoded_data}, 500
      assert Base.decode64!(encoded_data) == "Hello PTY"
    end
  end

  describe "terminate" do
    test "closes PTY session on channel leave" do
      socket = connect_socket("close-test")
      {:ok, _reply, socket} = Phoenix.ChannelTest.join(socket, "terminal:close-test", %{})
      assert_push "session_started", _

      # Record that create was called
      calls_before = CodePuppyControl.PtyManager.Stub.get_calls("close-test")
      assert Enum.any?(calls_before, fn {action, _} -> action == :create end)

      # Leave the channel — this triggers terminate/2 which calls PtyManager.close_session
      Phoenix.ChannelTest.leave(socket)
    end
  end
end
