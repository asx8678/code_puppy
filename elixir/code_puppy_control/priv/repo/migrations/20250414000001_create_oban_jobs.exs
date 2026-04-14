defmodule CodePuppyControl.Repo.Migrations.CreateObanJobs do
  @moduledoc """
  Creates Oban jobs table for SQLite.

  Oban v2.17+ supports SQLite via the Lite engine.
  """

  use Ecto.Migration

  def up do
    create table(:oban_jobs, primary_key: false, engine: :set) do
      add :id, :bigserial, primary_key: true
      add :state, :string, null: false, default: "available"
      add :queue, :string, null: false, default: "default"
      add :worker, :string, null: false
      add :args, :map, null: false, default: %{}
      add :meta, :map, null: false, default: %{}
      add :tags, {:array, :string}, null: false, default: []
      add :errors, {:array, :map}, null: false, default: []
      add :attempt, :integer, null: false, default: 0
      add :max_attempts, :integer, null: false, default: 20
      add :priority, :integer, null: false, default: 0

      add :attempted_at, :utc_datetime
      add :attempted_by, :string
      add :cancelled_at, :utc_datetime
      add :completed_at, :utc_datetime
      add :discarded_at, :utc_datetime
      add :inserted_at, :utc_datetime, null: false, default: fragment("datetime('now')")
      add :scheduled_at, :utc_datetime, null: false, default: fragment("datetime('now')")

      # Add indexes for performance
      timestamps()
    end

    create index(:oban_jobs, [:state, :queue, :scheduled_at], name: :oban_jobs_state_queue_scheduled_at_index)
    create index(:oban_jobs, [:state, :queue, :priority, :scheduled_at], name: :oban_jobs_state_queue_priority_scheduled_at_index)
  end

  def down do
    drop_if_exists index(:oban_jobs, [:state, :queue, :scheduled_at], name: :oban_jobs_state_queue_scheduled_at_index)
    drop_if_exists index(:oban_jobs, [:state, :queue, :priority, :scheduled_at], name: :oban_jobs_state_queue_priority_scheduled_at_index)
    drop table(:oban_jobs)
  end
end
