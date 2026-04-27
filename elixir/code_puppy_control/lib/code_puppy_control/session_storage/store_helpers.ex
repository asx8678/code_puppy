defmodule CodePuppyControl.SessionStorage.StoreHelpers do
  @moduledoc """
  Pure helper functions for SessionStorage.Store.

  Extracted to keep Store.ex under the 600-line cap. Contains:
  - ISO timestamp generation
  - Session entry construction
  - Terminal metadata normalization
  - ChatSession / session-data → ETS entry conversion
  - Session result formatting

  All functions are pure with no side effects. (code_puppy-ctj.1)
  """

  # ---------------------------------------------------------------------------
  # Timestamp
  # ---------------------------------------------------------------------------

  @doc "Returns the current UTC time as ISO 8601 string."
  @spec now_iso() :: String.t()
  def now_iso, do: DateTime.utc_now() |> DateTime.to_iso8601()

  # ---------------------------------------------------------------------------
  # Entry Construction
  # ---------------------------------------------------------------------------

  @doc "Builds an ETS session entry map from individual fields."
  @spec build_entry(
          String.t(),
          [map()],
          [String.t()],
          non_neg_integer(),
          boolean(),
          String.t(),
          boolean(),
          map() | nil
        ) :: map()
  def build_entry(name, history, compacted_hashes, total_tokens,
                  auto_saved, timestamp, has_terminal, terminal_meta) do
    %{
      name: name,
      history: history,
      compacted_hashes: compacted_hashes,
      total_tokens: total_tokens,
      message_count: length(history),
      auto_saved: auto_saved,
      timestamp: timestamp,
      has_terminal: has_terminal,
      terminal_meta: terminal_meta,
      updated_at: System.monotonic_time(:millisecond)
    }
  end

  # ---------------------------------------------------------------------------
  # Terminal Metadata Normalization
  # ---------------------------------------------------------------------------

  # Whitelist of known terminal_meta keys.  We never call String.to_atom/1
  # on persisted JSON / user-influenced data — only known keys are promoted
  # to atoms; unknown string keys are preserved as strings so downstream code
  # can still read them via dual-key access (get_key).  (code_puppy-ctj.1 fix)
  @terminal_meta_whitelist %{
    "session_id" => :session_id,
    "cols" => :cols,
    "rows" => :rows,
    "shell" => :shell,
    "attached_at" => :attached_at
  }

  @doc """
  Normalizes terminal metadata keys: promotes known string keys to atoms,
  preserves unknown string keys as strings.
  """
  @spec normalize_meta_keys(nil | map() | term()) :: nil | map() | term()
  def normalize_meta_keys(nil), do: nil
  def normalize_meta_keys(meta) when is_map(meta) do
    Map.new(meta, fn
      {k, v} when is_binary(k) ->
        {Map.get(@terminal_meta_whitelist, k, k), v}
      {k, v} when is_atom(k) ->
        {k, v}
    end)
  end
  def normalize_meta_keys(meta), do: meta

  @doc """
  Dual-key map accessor: tries atom key first, then string key fallback.

  Useful when reading data that may come from ETS (atom keys) or
  SQLite (string keys).
  """
  @spec get_key(map(), atom(), String.t(), term()) :: term()
  def get_key(map, atom_key, string_key, default \\ nil) do
    Map.get(map, atom_key, Map.get(map, string_key, default))
  end

  # ---------------------------------------------------------------------------
  # Session / Entry Conversion
  # ---------------------------------------------------------------------------

  @doc """
  Converts a ChatSession map (from SQLite) to an ETS entry.

  Handles the dual-key nature of data coming from SQLite (string keys)
  by normalizing via `get_key/4`. Terminal metadata keys are also
  normalized via `normalize_meta_keys/1`.
  """
  @spec chat_session_to_entry(map()) :: map()
  def chat_session_to_entry(session) when is_map(session) do
    raw_meta = get_key(session, :terminal_meta, "terminal_meta")
    %{
      name: get_key(session, :name, "name", ""),
      history: get_key(session, :history, "history", []),
      compacted_hashes: get_key(session, :compacted_hashes, "compacted_hashes", []),
      total_tokens: get_key(session, :total_tokens, "total_tokens", 0),
      message_count: get_key(session, :message_count, "message_count", 0),
      auto_saved: get_key(session, :auto_saved, "auto_saved", false),
      timestamp: get_key(session, :timestamp, "timestamp", ""),
      has_terminal: get_key(session, :has_terminal, "has_terminal", false),
      terminal_meta: normalize_meta_keys(raw_meta),
      updated_at: System.monotonic_time(:millisecond)
    }
  end

  @doc """
  Converts lightweight session data from `Sessions.load_session/1` to
  an ETS entry. Missing fields default to zero / empty values.
  """
  @spec session_data_to_entry(String.t(), map()) :: map()
  def session_data_to_entry(name, data) do
    history = Map.get(data, :history, [])
    %{
      name: name,
      history: history,
      compacted_hashes: Map.get(data, :compacted_hashes, []),
      total_tokens: 0,
      message_count: length(history),
      auto_saved: false,
      timestamp: "",
      has_terminal: false,
      terminal_meta: nil,
      updated_at: System.monotonic_time(:millisecond)
    }
  end

  @doc "Formats a ChatSession struct for API responses."
  @spec session_to_result(map()) :: map()
  def session_to_result(session) do
    %{
      name: session.name,
      message_count: session.message_count,
      total_tokens: session.total_tokens,
      auto_saved: session.auto_saved,
      timestamp: session.timestamp
    }
  end
end
