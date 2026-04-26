defmodule CodePuppyControl.Persistence.PersistedConfig do
  @moduledoc """
  Ecto schema for generic key-value configuration storage.

  Stores configuration entries in SQLite with namespaced keys and
  JSON-encoded values. Replaces file-based config persistence with
  Ecto-backed storage.
  """

  use Ecto.Schema
  import Ecto.Changeset

  @type t :: %__MODULE__{
          id: integer() | nil,
          key: String.t(),
          namespace: String.t(),
          value: map(),
          inserted_at: DateTime.t() | nil,
          updated_at: DateTime.t() | nil
        }

  schema "persisted_configs" do
    field(:key, :string)
    field(:namespace, :string, default: "default")
    field(:value, :map, default: %{})

    timestamps()
  end

  @doc """
  Creates a changeset for a persisted config entry.
  """
  @spec changeset(t() | Ecto.Changeset.t(), map()) :: Ecto.Changeset.t()
  def changeset(config, attrs) do
    config
    |> cast(attrs, [:key, :namespace, :value])
    |> validate_required([:key])
    |> validate_length(:key, max: 255)
    |> validate_length(:namespace, max: 128)
    |> unique_constraint([:namespace, :key],
      name: :persisted_configs_namespace_key_index
    )
  end

  @doc """
  Converts the config entry to a plain map.
  """
  @spec to_map(t()) :: map()
  def to_map(config) do
    %{
      id: config.id,
      key: config.key,
      namespace: config.namespace,
      value: config.value,
      inserted_at: config.inserted_at,
      updated_at: config.updated_at
    }
  end
end
