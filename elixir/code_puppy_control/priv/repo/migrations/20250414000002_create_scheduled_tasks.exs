defmodule CodePuppyControl.Repo.Migrations.CreateScheduledTasks do
  @moduledoc """
  Creates the scheduled_tasks table for the Oban scheduler.

  This table stores user-defined scheduled tasks that the scheduler
  daemon manages and executes via Oban jobs.
  """

  use Ecto.Migration

  def change do
    create table(:scheduled_tasks) do
      add :name, :string, null: false
      add :description, :text
      add :agent_name, :string, null: false
      add :model, :string
      add :prompt, :text, null: false
      add :config, :map, default: %{}
      add :schedule, :string  # Cron expression or nil for one-shot
      add :schedule_type, :string, default: "interval"  # interval, hourly, daily, cron
      add :schedule_value, :string, default: "1h"
      add :enabled, :boolean, default: true
      add :last_run_at, :utc_datetime
      add :last_status, :string  # success, failed, running
      add :last_exit_code, :integer
      add :last_error, :text
      add :run_count, :integer, default: 0
      add :working_directory, :string, default: "."
      add :log_file, :string

      timestamps()
    end

    create unique_index(:scheduled_tasks, [:name])
    create index(:scheduled_tasks, [:enabled])
    create index(:scheduled_tasks, [:schedule])
    create index(:scheduled_tasks, [:agent_name])
  end
end
