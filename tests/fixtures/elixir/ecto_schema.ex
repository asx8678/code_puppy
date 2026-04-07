# Test fixture: ecto_schema.ex
# Purpose: Ecto schema with fields and validations
# Expected symbols: 1 module (User), 1 schema, 3 functions (changeset, full_name, adult?)

defmodule MyApp.Accounts.User do
  @moduledoc """
  Ecto schema for User entity.
  Tests parsing of schema definitions, field declarations,
  associations, and changeset functions.
  """

  use Ecto.Schema
  import Ecto.Changeset

  @primary_key {:id, :binary_id, autogenerate: true}
  @foreign_key_type :binary_id
  schema "users" do
    # Regular fields
    field :email, :string
    field :name, :string
    field :age, :integer
    field :active, :boolean, default: true

    # Virtual fields (not persisted)
    field :password, :string, virtual: true
    field :password_confirmation, :string, virtual: true

    # Encrypted field
    field :password_hash, :string, redact: true

    # Associations
    has_many :posts, MyApp.Blog.Post
    belongs_to :organization, MyApp.Organizations.Organization
    many_to_many :roles, MyApp.Roles.Role, join_through: "user_roles"

    timestamps(type: :utc_datetime)
  end

  @doc false
  def changeset(user, attrs) do
    user
    |> cast(attrs, [:email, :name, :age, :password, :organization_id])
    |> validate_required([:email, :name])
    |> validate_format(:email, ~r/^[^\s]+@[^\s]+$/)
    |> validate_length(:password, min: 8)
    |> validate_number(:age, greater_than_or_equal_to: 0)
    |> unique_constraint(:email)
    |> put_password_hash()
  end

  @doc "Returns the full name of the user"
  def full_name(%__MODULE__{name: name}) when is_binary(name) do
    name
  end

  def full_name(_), do: "Anonymous"

  @doc "Checks if the user is an adult (18+)"
  def adult?(%__MODULE__{age: age}) when is_integer(age) do
    age >= 18
  end

  def adult?(_), do: false

  defp put_password_hash(%Ecto.Changeset{valid?: true, changes: %{password: password}} = changeset)
       when is_binary(password) do
    change(changeset, password_hash: Bcrypt.hash_pwd_salt(password))
  end

  defp put_password_hash(changeset), do: changeset
end
