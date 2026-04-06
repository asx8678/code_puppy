defmodule Mana.Commands.Session do
  @moduledoc """
  Session management commands.

  Provides commands for listing, creating, and deleting conversation sessions.

  ## Commands

  - `/session list` - List all sessions
  - `/session new` - Create a new session
  - `/session delete <id>` - Delete a session

  ## Examples

      /session list
      # Shows: Sessions: session_123456_789 - 2024-01-15 10:30:00

      /session new
      # Shows: Created session: session_123457_001

      /session delete session_123456_789
      # Shows: Deleted session: session_123456_789
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Session.Store, as: SessionStore

  @impl true
  def name, do: "/session"

  @impl true
  def description, do: "Manage conversation sessions"

  @impl true
  def usage, do: "/session [list|new|delete <id>]"

  @impl true
  def execute(["list"], _context) do
    case SessionStore.list_sessions() do
      [] -> {:ok, "No sessions available."}
      sessions -> format_sessions(sessions)
    end
  end

  def execute(["new"], _context) do
    session_id = SessionStore.create_session()
    {:ok, "Created session: #{session_id}"}
  end

  def execute(["delete", id], _context), do: do_delete_session(id)

  def execute([], _context) do
    {:ok, "Usage: #{usage()}"}
  end

  def execute(_args, _context) do
    {:ok, "Usage: #{usage()}"}
  end

  defp format_sessions(sessions) do
    active = SessionStore.active_session()

    lines =
      Enum.map(sessions, fn session_id ->
        marker = if session_id == active, do: " (active)", else: ""
        "  #{session_id}#{marker}"
      end)

    {:ok, ["Sessions:" | lines] |> Enum.join("\n")}
  end

  defp do_delete_session(id) do
    case SessionStore.delete_session(id) do
      :ok -> {:ok, "Deleted session: #{id}"}
      {:error, reason} -> {:error, "Failed to delete session: #{inspect(reason)}"}
    end
  end
end

defmodule Mana.Commands.Save do
  @moduledoc """
  Save the current session to disk.

  ## Usage

      /save

  Persists the current session messages to the session store.
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Session.Store, as: SessionStore

  @impl true
  def name, do: "/save"

  @impl true
  def description, do: "Save current session"

  @impl true
  def usage, do: "/save"

  @impl true
  def execute(_args, _context) do
    case SessionStore.active_session() do
      nil ->
        {:error, "No active session to save"}

      session_id ->
        case SessionStore.save(session_id) do
          :ok ->
            {:ok, "Session saved."}

          {:error, reason} ->
            {:error, "Failed to save session: #{inspect(reason)}"}
        end
    end
  end
end

defmodule Mana.Commands.Load do
  @moduledoc """
  Load a saved session.

  ## Usage

      /load <session_id>

  Restores a session from disk and sets it as the active session.
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Session.Store, as: SessionStore

  @impl true
  def name, do: "/load"

  @impl true
  def description, do: "Load a saved session"

  @impl true
  def usage, do: "/load <session_id>"

  @impl true
  def execute([id], _context) do
    case SessionStore.load(id) do
      {:ok, _messages} ->
        :ok = SessionStore.set_active_session(id)
        {:ok, "Loaded session: #{id}"}

      {:error, reason} ->
        {:error, "Failed to load session: #{inspect(reason)}"}
    end
  end

  def execute(_args, _context) do
    {:ok, "Usage: #{usage()}"}
  end
end

defmodule Mana.Commands.Compact do
  @moduledoc """
  Compact conversation history via summarization.

  Reduces the size of the conversation history by summarizing older messages,
  keeping only the most recent ones intact.

  ## Usage

      /compact

  Uses binary-split recursive summarization to reduce token count.
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Session.Store, as: SessionStore
  alias Mana.Summarization

  @impl true
  def name, do: "/compact"

  @impl true
  def description, do: "Compact conversation history via summarization"

  @impl true
  def usage, do: "/compact"

  @impl true
  def execute(_args, _context) do
    with {:ok, session_id} <- get_active_session(),
         messages <- SessionStore.get_history(session_id),
         true <- messages != [] do
      compact_and_store(session_id, messages)
    else
      false -> {:ok, "No messages to compact."}
      {:error, reason} -> {:error, reason}
    end
  end

  defp get_active_session do
    case SessionStore.active_session() do
      nil -> {:error, "No active session"}
      session_id -> {:ok, session_id}
    end
  end

  defp compact_and_store(session_id, messages) do
    original_count = length(messages)
    compacted = Summarization.compact_with_summary(messages)
    new_count = length(compacted)

    SessionStore.clear(session_id)

    Enum.each(compacted, fn msg ->
      SessionStore.append(session_id, msg)
    end)

    {:ok, "Compacted #{original_count} → #{new_count} messages."}
  end
end

defmodule Mana.Commands.Truncate do
  @moduledoc """
  Truncate conversation to last N messages.

  Keeps only the most recent N messages, discarding older ones.

  ## Usage

      /truncate <count>

  ## Examples

      /truncate 10
      # Keeps only the last 10 messages
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Session.Store, as: SessionStore

  @impl true
  def name, do: "/truncate"

  @impl true
  def description, do: "Truncate conversation to last N messages"

  @impl true
  def usage, do: "/truncate <count>"

  @impl true
  def execute([count_str], _context) do
    with {:ok, count} <- parse_count(count_str),
         {:ok, session_id} <- get_active_session(),
         messages <- SessionStore.get_history(session_id),
         true <- messages != [],
         {:ok, result} <- truncate_and_store(session_id, messages, count) do
      {:ok, result}
    else
      false -> {:ok, "No messages to truncate."}
      {:error, reason} -> {:error, reason}
    end
  end

  def execute(_args, _context) do
    {:ok, "Usage: #{usage()}"}
  end

  defp parse_count(count_str) do
    case Integer.parse(count_str) do
      {count, _} when count > 0 -> {:ok, count}
      _ -> {:error, "Invalid count: #{count_str}"}
    end
  end

  defp get_active_session do
    case SessionStore.active_session() do
      nil -> {:error, "No active session"}
      session_id -> {:ok, session_id}
    end
  end

  defp truncate_and_store(session_id, messages, count) do
    original_count = length(messages)
    truncated = Enum.take(messages, -count)

    SessionStore.clear(session_id)

    Enum.each(truncated, fn msg ->
      SessionStore.append(session_id, msg)
    end)

    {:ok, "Truncated to #{length(truncated)} messages (removed #{original_count - length(truncated)})."}
  end
end
