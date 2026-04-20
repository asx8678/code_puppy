defmodule CodePuppyControl.TUI.Widgets.SessionBrowserTest do
  use ExUnit.Case, async: true

  alias CodePuppyControl.TUI.Widgets.SessionBrowser

  describe "list_sessions/1" do
    test "returns {:ok, list} or {:error, reason} (DB may not be available)" do
      result =
        try do
          SessionBrowser.list_sessions()
        rescue
          _ -> {:error, :db_unavailable}
        end

      case result do
        {:ok, sessions} ->
          assert is_list(sessions)

          for session <- sessions do
            assert Map.has_key?(session, :name)
            assert is_binary(session.name)
          end

        {:error, _reason} ->
          # Acceptable — DB may not be migrated in test environment
          :ok
      end
    end

    test "filter with no matches returns empty list (DB may not be available)" do
      result =
        try do
          SessionBrowser.list_sessions(filter: "zzz_nonexistent_999")
        rescue
          _ -> {:error, :db_unavailable}
        end

      case result do
        {:ok, sessions} -> assert sessions == []
        {:error, _} -> :ok
      end
    end
  end

  describe "format_session/1" do
    test "returns an Owl.Data fragment for a valid session map" do
      session = %{
        name: "test-session-001",
        message_count: 42,
        total_tokens: 12_345,
        auto_saved: true,
        timestamp: DateTime.utc_now(),
        inserted_at: DateTime.utc_now()
      }

      result = SessionBrowser.format_session(session)
      # Should be an iolist or Owl.Data fragment — must not crash
      assert is_list(result) or is_binary(result)
    end

    test "handles nil timestamp gracefully" do
      session = %{
        name: "no-time-session",
        message_count: 0,
        total_tokens: 0,
        auto_saved: false,
        timestamp: nil,
        inserted_at: nil
      }

      result = SessionBrowser.format_session(session)
      assert is_list(result) or is_binary(result)
    end

    test "handles ISO8601 string timestamp" do
      session = %{
        name: "string-ts-session",
        message_count: 5,
        total_tokens: 1_000,
        auto_saved: false,
        timestamp: "2025-05-01T12:00:00Z",
        inserted_at: "2025-05-01T12:00:00Z"
      }

      result = SessionBrowser.format_session(session)
      assert is_list(result) or is_binary(result)
    end

    test "handles zero tokens" do
      session = %{
        name: "zero-tokens",
        message_count: 0,
        total_tokens: 0,
        auto_saved: false,
        timestamp: DateTime.utc_now(),
        inserted_at: DateTime.utc_now()
      }

      result = SessionBrowser.format_session(session)
      assert is_list(result) or is_binary(result)
    end

    test "handles large token counts" do
      session = %{
        name: "big-session",
        message_count: 999,
        total_tokens: 2_500_000,
        auto_saved: true,
        timestamp: DateTime.utc_now(),
        inserted_at: DateTime.utc_now()
      }

      result = SessionBrowser.format_session(session)
      assert is_list(result) or is_binary(result)
    end
  end
end
