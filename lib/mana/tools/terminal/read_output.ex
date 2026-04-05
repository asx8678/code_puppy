defmodule Mana.Tools.Terminal.ReadOutput do
  @moduledoc """
  Tool for reading terminal output and optionally matching a pattern.

  Extracts text from the terminal buffer. Can check for pattern matches.

  ## Examples

      {:ok, %{"output" => "hello world\\n", "line_count" => 1}} =
        Mana.Tools.Terminal.ReadOutput.execute(%{
          "lines" => 50
        })
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Terminal.PtyManager

  @impl true
  def name, do: "terminal_read_output"

  @impl true
  def description do
    "Read text from the terminal (scrapes xterm.js DOM).\n\n" <>
      "Use this when you need the actual text content, not just an image.\n\n" <>
      "Returns the output text content, line count, and success status."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        lines: %{
          type: "integer",
          description: "Number of lines to read from end (default: 50).",
          default: 50
        },
        pattern: %{
          type: "string",
          description: "Optional regex or text to search for."
        },
        capture_screenshot: %{
          type: "boolean",
          description: "Include a screenshot (default: False).",
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
    lines_count = Map.get(args, "lines", 50)
    pattern = Map.get(args, "pattern")
    session_id = resolve_session_id(args)

    case PtyManager.read_output(session_id) do
      {:ok, output} ->
        # Truncate to last N lines if specified
        truncated_output =
          output
          |> String.split("\n")
          |> Enum.take(-lines_count)
          |> Enum.join("\n")

        result = %{
          "success" => true,
          "output" => truncated_output,
          "line_count" => truncated_output |> String.split("\n") |> length()
        }

        result =
          if pattern do
            case Regex.run(~r/#{pattern}/, truncated_output) do
              nil -> Map.put(result, "matched", false)
              matches -> Map.put(result, "matched", true) |> Map.put("matches", matches)
            end
          else
            result
          end

        {:ok, result}

      {:error, {:session_not_found, sid}} ->
        {:error, "Terminal session not found: #{sid}. Open a session first with terminal_open."}

      {:error, :port_disconnected} ->
        {:error, "Terminal session disconnected."}

      {:error, reason} ->
        {:error, "Read output failed: #{inspect(reason)}"}
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
