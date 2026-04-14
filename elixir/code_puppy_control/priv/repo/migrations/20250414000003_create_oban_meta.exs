defmodule CodePuppyControl.Repo.Migrations.CreateObanMeta do
  @moduledoc """
  Creates the Oban meta table for job tracking in SQLite.

  Used by Oban.Engines.Lite for coordination and state management.
  """

  use Ecto.Migration

  def up do
    create table(:oban_meta, primary_key: false) do
      add :key, :string, primary_key: true, null: false
      add :value, :map, null: false, default: %{}
      add :inserted_at, :utc_datetime, null: false, default: fragment("datetime('now')")
      add :updated_at, :utc_datetime, null: false, default: fragment("datetime('now')")
    end

    # Insert initial values for Oban
    execute("INSERT INTO oban_meta (key, value) VALUES ('singleton', '{\"lock_version\": 0}') ON CONFLICT DO NOTHING")
  end

  def down do
    drop table(:oban_meta)
  end
end
