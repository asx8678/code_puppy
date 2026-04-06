defmodule Mana.Tools.Terminal.SendKeys do
  @moduledoc """
  Tool for sending raw keystrokes to a terminal session.

  Unlike `terminal_run_command`, this does NOT append a newline or wait
  for completion. Useful for sending individual keystrokes, control
  sequences, or partial input.

  ## Examples

      # Send Ctrl+C
      {:ok, %{"success" => true}} =
        Mana.Tools.Terminal.SendKeys.execute(%{
          "keys" => "c",
          "modifiers" => ["Control"],
          "session_id" => "a1b2c3d4"
        })

      # Send arrow up
      {:ok, %{"success" => true}} =
        Mana.Tools.Terminal.SendKeys.execute(%{
          "keys" => "ArrowUp",
          "repeat" => 3,
          "session_id" => "a1b2c3d4"
        })
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Terminal.PtyManager

  @impl true
  def name, do: "terminal_send_keys"

  @impl true
  def description do
    "Send special keys or key combinations to the terminal.\n\n" <>
      "Returns success status, keys sent, modifiers, and repeat count."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        keys: %{
          type: "string",
          description: "Key to send (e.g., \"Enter\", \"Tab\", \"ArrowUp\", \"ArrowDown\", \"c\")."
        },
        modifiers: %{
          type: "array",
          items: %{type: "string"},
          description: "Modifier keys like [\"Control\"] for Ctrl+C.",
          default: []
        },
        repeat: %{
          type: "integer",
          description: "Number of times to press the key (default: 1).",
          default: 1
        },
        delay_ms: %{
          type: "integer",
          description: "Milliseconds to wait between repeated keypresses (default: 50).",
          default: 50
        },
        session_id: %{
          type: "string",
          description: "The terminal session ID (optional if only one session is open)"
        }
      },
      required: ["keys"]
    }
  end

  @impl true
  def execute(args) do
    keys = Map.fetch!(args, "keys")
    modifiers = Map.get(args, "modifiers", [])
    repeat = Map.get(args, "repeat", 1)
    _delay_ms = Map.get(args, "delay_ms", 50)
    session_id = resolve_session_id(args)

    # Convert special key names to escape sequences
    key_data = translate_keys(keys, modifiers)

    # Send the key repeat times
    result =
      Enum.reduce_while(1..repeat, :ok, fn _i, :ok ->
        case PtyManager.send_keys(session_id, key_data) do
          :ok -> {:cont, :ok}
          error -> {:halt, error}
        end
      end)

    case result do
      :ok ->
        {:ok,
         %{
           "success" => true,
           "keys_sent" => keys,
           "modifiers" => modifiers,
           "repeat_count" => repeat
         }}

      {:error, {:session_not_found, sid}} ->
        {:error, "Terminal session not found: #{sid}. Open a session first with terminal_open."}

      {:error, :port_disconnected} ->
        {:error, "Terminal session disconnected."}

      {:error, reason} ->
        {:error, "Send keys failed: #{inspect(reason)}"}
    end
  rescue
    _e in KeyError ->
      {:error, "Missing required parameter: keys"}
  end

  # ---------------------------------------------------------------------------
  # Internal: Key Translation
  # ---------------------------------------------------------------------------

  # Translate special key names to terminal escape sequences
  @spec translate_keys(String.t(), [String.t()]) :: String.t()
  defp translate_keys(keys, modifiers) do
    base = translate_single_key(keys)

    case modifiers do
      [] ->
        base

      mods ->
        # For modifier keys, wrap with appropriate escape sequences
        Enum.reduce(mods, base, fn mod, acc ->
          case String.downcase(mod) do
            # Ctrl prefix
            "control" -> "\x03" <> acc
            # Alt/Meta prefix
            "alt" -> "\x1b" <> acc
            # Shift is handled by case
            "shift" -> acc
            "meta" -> "\x1b" <> acc
            _ -> acc
          end
        end)
    end
  end

  @spec translate_single_key(String.t()) :: String.t()
  defp translate_single_key(key) do
    case key do
      "Enter" -> "\r"
      "Tab" -> "\t"
      "Escape" -> "\x1b"
      "Backspace" -> "\x7f"
      "ArrowUp" -> "\x1b[A"
      "ArrowDown" -> "\x1b[B"
      "ArrowRight" -> "\x1b[C"
      "ArrowLeft" -> "\x1b[D"
      "Home" -> "\x1b[H"
      "End" -> "\x1b[F"
      "PageUp" -> "\x1b[5~"
      "PageDown" -> "\x1b[6~"
      "Delete" -> "\x1b[3~"
      "Insert" -> "\x1b[2~"
      "F1" -> "\x1bOP"
      "F2" -> "\x1bOQ"
      "F3" -> "\x1bOR"
      "F4" -> "\x1bOS"
      "F5" -> "\x1b[15~"
      "F6" -> "\x1b[17~"
      "F7" -> "\x1b[18~"
      "F8" -> "\x1b[19~"
      "F9" -> "\x1b[20~"
      "F10" -> "\x1b[21~"
      "F11" -> "\x1b[23~"
      "F12" -> "\x1b[24~"
      single when byte_size(single) == 1 -> single
      other -> other
    end
  end

  defp resolve_session_id(args) do
    case Map.get(args, "session_id") do
      nil ->
        sessions = Mana.Tools.Terminal.PtyManager.list_sessions()

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
