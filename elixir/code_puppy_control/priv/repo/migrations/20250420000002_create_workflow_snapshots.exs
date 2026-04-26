defmodule CodePuppyControl.Repo.Migrations.CreateWorkflowSnapshots do
  @moduledoc """
  Creates the workflow_snapshots table for persisting point-in-time
  workflow state snapshots.

  Enables load/save roundtrips of WorkflowState to SQLite, supporting
  crash recovery and session resumption per §4.1 (domain truth is persistent).
  """

  use Ecto.Migration

  def change do
    execute("""
    CREATE TABLE IF NOT EXISTS workflow_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      session_id TEXT NOT NULL,
      flags TEXT NOT NULL DEFAULT '[]',
      metadata TEXT NOT NULL DEFAULT '{}',
      start_time INTEGER,
      inserted_at TEXT DEFAULT (datetime('now')) NOT NULL,
      updated_at TEXT DEFAULT (datetime('now')) NOT NULL
    )
    """)

    execute(
      "CREATE INDEX IF NOT EXISTS workflow_snapshots_session_id_index ON workflow_snapshots(session_id)"
    )

    execute(
      "CREATE INDEX IF NOT EXISTS workflow_snapshots_inserted_at_index ON workflow_snapshots(inserted_at)"
    )
  end
end
