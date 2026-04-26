defmodule CodePuppyControl.Persistence.WorkflowSnapshot do
  @moduledoc """
  Ecto schema for persisting point-in-time workflow state snapshots.

  Enables crash recovery and session resumption by serializing
  WorkflowState flags and metadata to SQLite. Per §4.1, domain truth
  is persistent — the database row is the source of truth, not the
  Agent process state.
  """

  use Ecto.Schema
  import Ecto.Changeset

  @type t :: %__MODULE__{
          id: integer() | nil,
          session_id: String.t(),
          flags: list(String.t()),
          metadata: map(),
          start_time: integer() | nil,
          inserted_at: DateTime.t() | nil,
          updated_at: DateTime.t() | nil
        }

  schema "workflow_snapshots" do
    field(:session_id, :string)
    field(:flags, {:array, :string}, default: [])
    field(:metadata, :map, default: %{})
    field(:start_time, :integer)

    timestamps()
  end

  @doc """
  Creates a changeset for a workflow snapshot.
  """
  @spec changeset(t() | Ecto.Changeset.t(), map()) :: Ecto.Changeset.t()
  def changeset(snapshot, attrs) do
    snapshot
    |> cast(attrs, [:session_id, :flags, :metadata, :start_time])
    |> validate_required([:session_id])
    |> validate_length(:session_id, max: 255)
  end

  @doc """
  Converts the snapshot to a plain map.
  """
  @spec to_map(t()) :: map()
  def to_map(snapshot) do
    %{
      id: snapshot.id,
      session_id: snapshot.session_id,
      flags: snapshot.flags,
      metadata: snapshot.metadata,
      start_time: snapshot.start_time,
      inserted_at: snapshot.inserted_at,
      updated_at: snapshot.updated_at
    }
  end
end
