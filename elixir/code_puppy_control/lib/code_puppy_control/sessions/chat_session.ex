defmodule CodePuppyControl.Sessions.ChatSession do
  @moduledoc """
  Ecto schema for persisting agent chat sessions.

  Implements : Store session history, compacted hashes, and metadata
  in SQLite via Ecto instead of JSON files.
  """

  use Ecto.Schema
  import Ecto.Changeset

  alias CodePuppyControl.Repo

  @type t :: %__MODULE__{
          id: integer() | nil,
          name: String.t(),
          history: list(map()),
          compacted_hashes: list(String.t()),
          total_tokens: non_neg_integer(),
          message_count: non_neg_integer(),
          auto_saved: boolean(),
          timestamp: String.t() | nil,
          inserted_at: DateTime.t() | nil,
          updated_at: DateTime.t() | nil
        }

  schema "chat_sessions" do
    field(:name, :string)
    field(:history, {:array, :map}, default: [])
    field(:compacted_hashes, {:array, :string}, default: [])
    field(:total_tokens, :integer, default: 0)
    field(:message_count, :integer, default: 0)
    field(:auto_saved, :boolean, default: false)
    field(:timestamp, :string)

    timestamps()
  end

  @doc """
  Creates a changeset for a chat session.
  """
  @spec changeset(t() | Ecto.Changeset.t(), map()) :: Ecto.Changeset.t()
  def changeset(session, attrs) do
    session
    |> cast(attrs, [
      :name,
      :history,
      :compacted_hashes,
      :total_tokens,
      :message_count,
      :auto_saved,
      :timestamp
    ])
    |> validate_required([:name])
    |> validate_length(:name, max: 255)
    |> unique_constraint(:name, name: :chat_sessions_name_index)
  end

  @doc """
  Converts the session to a serializable map.
  """
  @spec to_map(t()) :: map()
  def to_map(session) do
    %{
      id: session.id,
      name: session.name,
      history: session.history,
      compacted_hashes: session.compacted_hashes,
      total_tokens: session.total_tokens,
      message_count: session.message_count,
      auto_saved: session.auto_saved,
      timestamp: session.timestamp,
      inserted_at: session.inserted_at,
      updated_at: session.updated_at
    }
  end
end
