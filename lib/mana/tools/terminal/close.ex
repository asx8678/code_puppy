defmodule Mana.Tools.Terminal.Close do
  @moduledoc """
  Tool for closing a terminal session and cleaning up resources.

  Terminates the shell process and removes the session from the registry.

  ## Examples

      {:ok, %{"success" => true}} =
        Mana.Tools.Terminal.Close.execute(%{"session_id" => "a1b2c3d4"})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Terminal.PtyManager

  @impl true
  def name, do: "terminal_close"

  @impl true
  def description do
    "Close the terminal browser and clean up resources."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        session_id: %{
          type: "string",
          description: "The terminal session ID to close (optional if only one session is open)"
        }
      },
      required: []
    }
  end

  @impl true
  def execute(args) do
    session_id = resolve_session_id(args)

    case PtyManager.close_session(session_id) do
      :ok ->
        {:ok, %{"success" => true, "message" => "Terminal session #{session_id} closed."}}

      {:error, {:session_not_found, sid}} ->
        {:error, "Terminal session not found: #{sid}. It may have already been closed."}

      {:error, reason} ->
        {:error, "Failed to close terminal session: #{inspect(reason)}"}
    end
  end

  defp resolve_session_id(args) do
    case Map.get(args, "session_id") do
      nil ->
        sessions = PtyManager.list_sessions()

        case sessions do
          [single] -> single
          [] -> raise "No terminal sessions open."
          _multiple -> raise "Multiple sessions open. Specify session_id parameter."
        end

      id ->
        id
    end
  end
end
