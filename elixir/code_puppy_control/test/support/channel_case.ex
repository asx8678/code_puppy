defmodule CodePuppyControlWeb.ChannelCase do
  @moduledoc """
  Shared test case for Phoenix Channel tests.

  Sets up the socket and connects through UserSocket, enabling
  `Phoenix.ChannelTest` helpers for join/push/leave assertions.

  ## Token handling

  In the test environment, `websocket_secret` is set to a known value.
  This module generates a valid signed token for the provided session ID
  so that `UserSocket.connect/3` accepts the connection.
  """

  use ExUnit.CaseTemplate

  using do
    quote do
      import Phoenix.ChannelTest

      alias CodePuppyControlWeb.UserSocket

      # The endpoint for channel tests
      @endpoint CodePuppyControlWeb.Endpoint

      import CodePuppyControlWeb.ChannelCase
    end
  end

  setup _tags do
    # Ensure PubSub is running for channel tests
    case CodePuppyControl.PubSub |> Process.whereis() do
      nil ->
        {:ok, _} = Phoenix.PubSub.PG2.start_link(name: CodePuppyControl.PubSub)

      _pid ->
        :ok
    end

    # Ensure EventStore is running
    case Process.whereis(CodePuppyControl.EventStore) do
      nil ->
        {:ok, _} = CodePuppyControl.EventStore.start_link([])

      _pid ->
        :ok
    end

    # Use the stub PTY manager for terminal channel tests
    Application.put_env(:code_puppy_control, :pty_manager, CodePuppyControl.PtyManager.Stub)

    # Ensure stub agent is started (may already be running from app supervision)
    case Process.whereis(CodePuppyControl.PtyManager.Stub) do
      nil ->
        {:ok, _} = CodePuppyControl.PtyManager.Stub.start_link([])

      _pid ->
        :ok
    end

    # Clean stub state between tests
    try do
      CodePuppyControl.PtyManager.Stub.clear_all()
    catch
      :exit, _ -> :ok
    end

    :ok
  end

  @doc """
  Connect a socket for testing with a signed token for "test-session".

  Uses the test `websocket_secret` to sign a valid token so that
  `UserSocket.connect/3` accepts the connection in test env.
  """
  @spec connect_socket() :: Phoenix.Socket.t()
  defmacro connect_socket do
    quote do
      token =
        Phoenix.Token.sign(
          CodePuppyControlWeb.Endpoint,
          Application.get_env(:code_puppy_control, :websocket_secret),
          "test-session"
        )

      {:ok, socket} =
        Phoenix.ChannelTest.connect(
          CodePuppyControlWeb.UserSocket,
          %{"token" => token}
        )

      socket
    end
  end

  @doc """
  Connect a socket with a specific session ID in the token.

  The session ID must match the channel topic you intend to join,
  e.g. `connect_socket("my-session")` → join `"events:my-session"`.
  """
  @spec connect_socket(String.t()) :: Phoenix.Socket.t()
  defmacro connect_socket(session_id) do
    quote do
      token =
        Phoenix.Token.sign(
          CodePuppyControlWeb.Endpoint,
          Application.get_env(:code_puppy_control, :websocket_secret),
          unquote(session_id)
        )

      {:ok, socket} =
        Phoenix.ChannelTest.connect(
          CodePuppyControlWeb.UserSocket,
          %{"token" => token}
        )

      socket
    end
  end
end
