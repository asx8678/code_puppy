defmodule Mana.Tools.Terminal.Screenshot do
  @moduledoc """
  Tool for capturing terminal state as text for analysis.

  Returns a textual representation of the terminal state, including
  session metadata and the current output buffer content. Unlike a
  visual screenshot (as in browser tools), this captures the terminal
  as structured text data suitable for LLM analysis.

  ## Examples

      {:ok, %{"session_id" => "a1b2c3d4", "buffer_size" => 1024, "output" => "..."}} =
        Mana.Tools.Terminal.Screenshot.execute(%{"full_page" => false})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Terminal.PtyManager

  @impl true
  def name, do: "terminal_screenshot_analyze"

  @impl true
  def description do
    "Take a screenshot of the terminal browser.\n\n" <>
      "Returns the screenshot via ToolReturn with BinaryContent that you can " <>
      "see directly. Use this to see what's displayed in the terminal."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        full_page: %{
          type: "boolean",
          description: "Capture full page (True) or just viewport (False).",
          default: false
        },
        session_id: %{
          type: "string",
          description: "The terminal session ID (optional if only one session is open)"
        }
      },
      required: []
    }
  end

  @impl true
  def execute(args) do
    session_id = resolve_session_id(args)
    _full_page = Map.get(args, "full_page", false)

    with {:ok, info} <- PtyManager.get_session_info(session_id),
         {:ok, output} <- PtyManager.read_output(session_id) do
      # Build a text representation of the terminal state
      separator = String.duplicate("═", 60)

      text_capture = """
      #{separator}
      Terminal Session: #{info.session_id}
      Shell: #{info.shell}
      Status: #{info.status}
      Buffer Size: #{info.buffer_size} bytes
      #{separator}
      #{output}
      #{separator}
      """

      {:ok,
       %{
         "success" => true,
         "session_id" => info.session_id,
         "status" => to_string(info.status),
         "buffer_size" => info.buffer_size,
         "output" => text_capture
       }}
    else
      {:error, {:session_not_found, sid}} ->
        {:error, "Terminal session not found: #{sid}. Open a session first with terminal_open."}

      {:error, :port_disconnected} ->
        {:error, "Terminal session disconnected."}

      {:error, reason} ->
        {:error, "Screenshot failed: #{inspect(reason)}"}
    end
  end

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
