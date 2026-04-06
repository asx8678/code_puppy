defmodule Mana.Tools.Terminal.Open do
  @moduledoc """
  Tool for opening a new PTY terminal session.

  Creates an interactive shell session via `Mana.Tools.Terminal.PtyManager`
  and returns the session ID for use with other terminal tools.

  ## Examples

      {:ok, %{"session_id" => "a1b2c3d4e5f6"}} =
        Mana.Tools.Terminal.Open.execute(%{})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Terminal.PtyManager

  @impl true
  def name, do: "terminal_open"

  @impl true
  def description do
    "Open the terminal browser interface.\n\n" <>
      "First checks if the API server is running, then opens a browser " <>
      "to the terminal endpoint. Waits for xterm.js to load.\n\n" <>
      "Returns a session_id that can be used with other terminal tools."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        host: %{
          type: "string",
          description: "The hostname where the server is running (default: localhost)",
          default: "localhost"
        },
        port: %{
          type: "integer",
          description: "The port number for the server (default: 8765)",
          default: 8765
        }
      },
      required: []
    }
  end

  @impl true
  def execute(args) do
    shell = System.get_env("SHELL") || "/bin/bash"
    timeout = Map.get(args, "timeout", 30_000)

    opts = [
      shell: shell,
      timeout: timeout
    ]

    case PtyManager.open_session(opts) do
      {:ok, session_id} ->
        {:ok,
         %{
           "success" => true,
           "session_id" => session_id,
           "message" => "Terminal session opened. Use session_id with terminal_run_command, terminal_send_keys, etc."
         }}

      {:error, reason} ->
        {:error, "Failed to open terminal session: #{inspect(reason)}"}
    end
  end
end
