defmodule CodePuppyControl.Tools.StagedChanges.StagedChange do
  @moduledoc """
  A single staged change entry.

  Validates that `applied` and `rejected` are not both `true`,
  matching the Python `__post_init__` guard.
  """

  @derive Jason.Encoder
  @enforce_keys [:change_id, :change_type, :file_path]
  defstruct [
    :change_id,
    :change_type,
    :file_path,
    :content,
    :old_str,
    :new_str,
    :snippet,
    :description,
    created_at: nil,
    applied: false,
    rejected: false
  ]

  @type t :: %__MODULE__{}

  @doc """
  Create a new StagedChange with validation.

  Raises `ArgumentError` if both `applied` and `rejected` are true,
  matching the Python ValueError guard.
  """
  @spec new(keyword()) :: t()
  def new(opts) do
    struct!(__MODULE__, opts)
    |> validate!()
  end

  defp validate!(%__MODULE__{applied: true, rejected: true}) do
    raise ArgumentError, "StagedChange cannot be both applied and rejected"
  end

  defp validate!(change), do: change

  @doc """
  Serialize change to map (matches Python `to_dict`).
  """
  @spec to_map(t()) :: map()
  def to_map(%__MODULE__{} = c) do
    %{
      "change_id" => c.change_id,
      "change_type" => Atom.to_string(c.change_type),
      "file_path" => c.file_path,
      "content" => c.content,
      "old_str" => c.old_str,
      "new_str" => c.new_str,
      "snippet" => c.snippet,
      "created_at" => c.created_at,
      "description" => c.description,
      "applied" => c.applied,
      "rejected" => c.rejected
    }
  end

  @doc """
  Deserialize change from map (matches Python `from_dict`).
  """
  @spec from_map(map()) :: t()
  def from_map(data) when is_map(data) do
    type_atom =
      case data["change_type"] do
        t when is_atom(t) -> t
        t when is_binary(t) -> String.to_existing_atom(t)
      end

    %__MODULE__{
      change_id: data["change_id"],
      change_type: type_atom,
      file_path: data["file_path"],
      content: data["content"],
      old_str: data["old_str"],
      new_str: data["new_str"],
      snippet: data["snippet"],
      created_at: data["created_at"],
      description: data["description"] || "",
      applied: data["applied"] || false,
      rejected: data["rejected"] || false
    }
  end
end
