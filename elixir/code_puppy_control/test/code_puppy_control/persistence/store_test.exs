defmodule CodePuppyControl.Persistence.StoreTest do
  @moduledoc """
  Integration tests for `CodePuppyControl.Persistence.Store` CRUD operations.

  Tests roundtrip persistence of configs, workflow snapshots, and sessions
  to SQLite via Ecto.
  """

  use ExUnit.Case, async: false

  alias CodePuppyControl.Persistence.{PersistedConfig, Store, WorkflowSnapshot}
  alias CodePuppyControl.Sessions.ChatSession

  setup do
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(CodePuppyControl.Repo)

    # SQLite doesn't support true sandbox isolation in all modes;
    # explicitly truncate between tests for deterministic runs.
    CodePuppyControl.Repo.delete_all(PersistedConfig)
    CodePuppyControl.Repo.delete_all(WorkflowSnapshot)
    CodePuppyControl.Repo.delete_all(ChatSession)

    :ok
  end

  # ── Config CRUD ───────────────────────────────────────────────────────────

  describe "create/2 :config" do
    test "creates a config with key and value" do
      assert {:ok, %PersistedConfig{} = config} =
               Store.create(:config, %{key: "theme", value: %{"color" => "dark"}})

      assert config.key == "theme"
      assert config.namespace == "default"
      assert config.value == %{"color" => "dark"}
    end

    test "creates a config with custom namespace" do
      assert {:ok, config} =
               Store.create(:config, %{
                 key: "model",
                 namespace: "agents",
                 value: %{"name" => "claude"}
               })

      assert config.namespace == "agents"
    end

    test "returns error changeset for missing key" do
      assert {:error, changeset} = Store.create(:config, %{value: %{}})
      assert %{key: _} = errors_on(changeset)
    end

    test "returns error changeset for duplicate namespace+key" do
      Store.create(:config, %{key: "dup", value: %{}})
      assert {:error, _changeset} = Store.create(:config, %{key: "dup", value: %{}})
    end
  end

  describe "get/2 :config" do
    test "retrieves existing config" do
      Store.create(:config, %{key: "fetch_me", value: %{"a" => 1}})
      assert {:ok, config} = Store.get(:config, "fetch_me")
      assert config.key == "fetch_me"
      assert config.value == %{"a" => 1}
    end

    test "returns :not_found for missing key" do
      assert {:error, :not_found} = Store.get(:config, "no_such_key")
    end
  end

  describe "get_config/2" do
    test "retrieves by namespace and key" do
      Store.create(:config, %{key: "ns_test", namespace: "custom", value: %{"x" => 42}})
      assert {:ok, config} = Store.get_config("custom", "ns_test")
      assert config.value == %{"x" => 42}
    end

    test "returns :not_found for wrong namespace" do
      Store.create(:config, %{key: "ns_only", namespace: "a", value: %{}})
      assert {:error, :not_found} = Store.get_config("b", "ns_only")
    end
  end

  describe "update/3 :config" do
    test "updates an existing config" do
      Store.create(:config, %{key: "updatable", value: %{"v" => 1}})
      assert {:ok, updated} = Store.update(:config, "updatable", %{value: %{"v" => 2}})
      assert updated.value == %{"v" => 2}
    end

    test "returns :not_found for missing config" do
      assert {:error, :not_found} = Store.update(:config, "ghost", %{value: %{}})
    end
  end

  describe "delete/2 :config" do
    test "deletes an existing config" do
      Store.create(:config, %{key: "deleteme", value: %{}})
      assert :ok = Store.delete(:config, "deleteme")
      assert {:error, :not_found} = Store.get(:config, "deleteme")
    end

    test "returns :not_found for missing config" do
      assert {:error, :not_found} = Store.delete(:config, "nope")
    end
  end

  describe "list/2 :config" do
    test "lists all configs" do
      Store.create(:config, %{key: "list_a", value: %{}})
      Store.create(:config, %{key: "list_b", value: %{}})
      configs = Store.list(:config)
      keys = Enum.map(configs, & &1.key)
      assert "list_a" in keys
      assert "list_b" in keys
    end

    test "filters by namespace" do
      Store.create(:config, %{key: "ns_filter_1", namespace: "filter_ns", value: %{}})
      Store.create(:config, %{key: "ns_filter_2", namespace: "other", value: %{}})
      configs = Store.list(:config, namespace: "filter_ns")
      assert length(configs) == 1
      assert hd(configs).key == "ns_filter_1"
    end

    test "respects limit" do
      for i <- 1..5, do: Store.create(:config, %{key: "limit_#{i}", value: %{}})
      configs = Store.list(:config, limit: 3)
      assert length(configs) == 3
    end
  end

  describe "put_config/2 and put_config/3" do
    test "creates new config on first call" do
      assert {:ok, config} = Store.put_config("new_key", %{"a" => 1})
      assert config.value == %{"a" => 1}
    end

    test "updates existing config on second call" do
      Store.put_config("upsert_key", %{"v" => 1})
      assert {:ok, updated} = Store.put_config("upsert_key", %{"v" => 2})
      assert updated.value == %{"v" => 2}
    end

    test "put_config with namespace" do
      assert {:ok, config} = Store.put_config("myns", "ns_key", %{"b" => 3})
      assert config.namespace == "myns"
      assert config.value == %{"b" => 3}
    end
  end

  # ── Workflow Snapshot CRUD ────────────────────────────────────────────────

  describe "create/2 :workflow_snapshot" do
    test "creates a snapshot with flags and metadata" do
      attrs = %{
        session_id: "sess-001",
        flags: ["did_generate_code", "did_execute_shell"],
        metadata: %{"agent_name" => "test-agent"},
        start_time: System.system_time(:second)
      }

      assert {:ok, %WorkflowSnapshot{} = snap} = Store.create(:workflow_snapshot, attrs)
      assert snap.session_id == "sess-001"
      assert "did_generate_code" in snap.flags
      assert snap.metadata["agent_name"] == "test-agent"
    end

    test "returns error for missing session_id" do
      assert {:error, changeset} = Store.create(:workflow_snapshot, %{flags: []})
      assert %{session_id: _} = errors_on(changeset)
    end
  end

  describe "get/2 :workflow_snapshot" do
    test "retrieves latest snapshot by session_id" do
      Store.create(:workflow_snapshot, %{session_id: "s1", flags: ["did_generate_code"]})
      assert {:ok, snap} = Store.get(:workflow_snapshot, "s1")
      assert snap.session_id == "s1"
    end

    test "returns :not_found for missing session" do
      assert {:error, :not_found} = Store.get(:workflow_snapshot, "no_session")
    end
  end

  describe "update/3 :workflow_snapshot" do
    test "updates flags on existing snapshot" do
      Store.create(:workflow_snapshot, %{session_id: "s2", flags: []})
      assert {:ok, updated} = Store.update(:workflow_snapshot, "s2", %{flags: ["did_run_tests"]})
      assert updated.flags == ["did_run_tests"]
    end
  end

  describe "delete/2 :workflow_snapshot" do
    test "deletes existing snapshot" do
      Store.create(:workflow_snapshot, %{session_id: "s3", flags: []})
      assert :ok = Store.delete(:workflow_snapshot, "s3")
      assert {:error, :not_found} = Store.get(:workflow_snapshot, "s3")
    end
  end

  describe "list/2 :workflow_snapshot" do
    test "lists all snapshots" do
      Store.create(:workflow_snapshot, %{session_id: "l1", flags: []})
      Store.create(:workflow_snapshot, %{session_id: "l2", flags: []})
      snaps = Store.list(:workflow_snapshot)
      session_ids = Enum.map(snaps, & &1.session_id)
      assert "l1" in session_ids
      assert "l2" in session_ids
    end

    test "filters by session_id" do
      Store.create(:workflow_snapshot, %{session_id: "filter_s", flags: []})
      Store.create(:workflow_snapshot, %{session_id: "other_s", flags: []})
      snaps = Store.list(:workflow_snapshot, session_id: "filter_s")
      assert length(snaps) == 1
    end
  end

  # ── Session CRUD ──────────────────────────────────────────────────────────

  describe "create/2 :session" do
    test "creates a chat session" do
      assert {:ok, %ChatSession{} = session} =
               Store.create(:session, %{name: "test-session", history: []})

      assert session.name == "test-session"
    end
  end

  describe "get/2 :session" do
    test "retrieves existing session" do
      Store.create(:session, %{name: "get-session"})
      assert {:ok, session} = Store.get(:session, "get-session")
      assert session.name == "get-session"
    end

    test "returns :not_found for missing session" do
      assert {:error, :not_found} = Store.get(:session, "ghost-session")
    end
  end

  describe "list/2 :session" do
    test "lists sessions" do
      Store.create(:session, %{name: "ls_a"})
      Store.create(:session, %{name: "ls_b"})
      sessions = Store.list(:session)
      names = Enum.map(sessions, & &1.name)
      assert "ls_a" in names
      assert "ls_b" in names
    end
  end

  describe "delete/2 :session" do
    test "deletes existing session" do
      Store.create(:session, %{name: "del-session"})
      assert :ok = Store.delete(:session, "del-session")
      assert {:error, :not_found} = Store.get(:session, "del-session")
    end
  end

  # ── Cross-entity roundtrip ────────────────────────────────────────────────

  describe "roundtrip: config create → get → update → delete" do
    test "full lifecycle" do
      # Create
      assert {:ok, config} = Store.create(:config, %{key: "lifecycle", value: %{"step" => 1}})
      id = config.id

      # Read
      assert {:ok, fetched} = Store.get(:config, "lifecycle")
      assert fetched.id == id
      assert fetched.value["step"] == 1

      # Update
      assert {:ok, updated} = Store.update(:config, "lifecycle", %{value: %{"step" => 2}})
      assert updated.id == id
      assert updated.value["step"] == 2

      # Verify update persisted
      assert {:ok, refetched} = Store.get(:config, "lifecycle")
      assert refetched.value["step"] == 2

      # Delete
      assert :ok = Store.delete(:config, "lifecycle")
      assert {:error, :not_found} = Store.get(:config, "lifecycle")
    end
  end

  describe "roundtrip: workflow snapshot create → get → update → delete" do
    test "full lifecycle" do
      # Create
      assert {:ok, _snap} =
               Store.create(:workflow_snapshot, %{
                 session_id: "rt-session",
                 flags: ["did_generate_code"],
                 metadata: %{"count" => 1},
                 start_time: 1_000_000
               })

      # Read
      assert {:ok, fetched} = Store.get(:workflow_snapshot, "rt-session")
      assert "did_generate_code" in fetched.flags

      # Update
      assert {:ok, updated} =
               Store.update(:workflow_snapshot, "rt-session", %{
                 flags: ["did_generate_code", "did_run_tests"],
                 metadata: %{"count" => 2}
               })

      assert length(updated.flags) == 2
      assert updated.metadata["count"] == 2

      # Delete
      assert :ok = Store.delete(:workflow_snapshot, "rt-session")
      assert {:error, :not_found} = Store.get(:workflow_snapshot, "rt-session")
    end
  end

  # ── Helpers ───────────────────────────────────────────────────────────────

  defp errors_on(changeset) do
    Ecto.Changeset.traverse_errors(changeset, fn {msg, opts} ->
      Regex.replace(~r"%{(\w+)}", msg, fn _, key ->
        opts |> Keyword.get(String.to_existing_atom(key), key) |> to_string()
      end)
    end)
  end
end
