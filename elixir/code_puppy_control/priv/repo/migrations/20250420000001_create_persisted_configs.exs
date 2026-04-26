defmodule CodePuppyControl.Repo.Migrations.CreatePersistedConfigs do
  @moduledoc """
  Creates the persisted_configs table for generic key-value config storage.

  Provides Ecto-backed persistence for configuration entries that were
  previously stored only in JSON files. Supports namespaced keys and
  JSON-encoded values.
  """

  use Ecto.Migration

  def change do
    execute("""
    CREATE TABLE IF NOT EXISTS persisted_configs (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      key TEXT NOT NULL,
      namespace TEXT NOT NULL DEFAULT 'default',
      value TEXT NOT NULL DEFAULT '{}',
      inserted_at TEXT DEFAULT (datetime('now')) NOT NULL,
      updated_at TEXT DEFAULT (datetime('now')) NOT NULL
    )
    """)

    execute(
      "CREATE UNIQUE INDEX IF NOT EXISTS persisted_configs_namespace_key_index ON persisted_configs(namespace, key)"
    )

    execute(
      "CREATE INDEX IF NOT EXISTS persisted_configs_namespace_index ON persisted_configs(namespace)"
    )
  end
end
