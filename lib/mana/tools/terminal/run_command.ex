defmodule Mana.Tools.Terminal.RunCommand do
  @moduledoc """
  Tool for executing a command in a terminal session.

  Sends the command to the shell and waits for completion using
  sentinel-based detection. Returns the command output.

  ## Examples

      {:ok, %{"output" => "hello\\n"}} =
        Mana.Tools.Terminal.RunCommand.execute(%{
          "command" => "echo hello",
          "session_id" => "a1b2c3d4"
        })
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Terminal.PtyManager

  @impl true
  def name, do: "terminal_run_command"

  @impl true
  def description do
    "Execute a command in the terminal browser.\n\n" <>
      "Types the command and presses Enter. Optionally captures a screenshot " <>
      "that you can see directly as base64 image data.\n\n" <>
      "Returns command output, optionally with a screenshot."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        command: %{
          type: "string",
          description: "The command to execute."
        },
        session_id: %{
          type: "string",
          description: "The terminal session ID (optional if only one session is open)"
        },
        wait_for_prompt: %{
          type: "boolean",
          description: "Wait briefly for command to process (default: True)",
          default: true
        },
        capture_screenshot: %{
          type: "boolean",
          description:
            "Capture screenshot after execution (default: False). Set True if you need to see the terminal output visually.",
          default: false
        }
      },
      required: ["command"]
    }
  end

  @impl true
  def execute(args) do
    command = Map.fetch!(args, "command")
    session_id = resolve_session_id(args)

    case PtyManager.run_command(session_id, command) do
      {:ok, output} ->
        result = %{
          "success" => true,
          "command" => command,
          "output" => output
        }

        {:ok, result}

      {:error, {:session_not_found, sid}} ->
        {:error, "Terminal session not found: #{sid}. Open a session first with terminal_open."}

      {:error, :port_disconnected} ->
        {:error, "Terminal session disconnected. The shell process may have crashed."}

      {:error, :command_in_progress} ->
        {:error, "Another command is already running in this session. Wait for it to complete."}

      {:error, reason} ->
        {:error, "Command execution failed: #{inspect(reason)}"}
    end
  rescue
    _e in KeyError ->
      {:error, "Missing required parameter: command"}
  end

  # ---------------------------------------------------------------------------
  # Internal
  # ---------------------------------------------------------------------------

  defp resolve_session_id(args) do
    case Map.get(args, "session_id") do
      nil ->
        sessions = PtyManager.list_sessions()

        case sessions do
          [single] -> single
          [] -> raise "No terminal sessions open. Use terminal_open first."
          _multiple -> raise "Multiple sessions open. Specify session_id parameter."
        end

      id ->
        id
    end
  end
end
