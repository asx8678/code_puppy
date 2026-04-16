# Test fixture: phoenix_controller.ex
# Purpose: Phoenix controller with actions
# Expected symbols: 1 module (UserController), 5+ action functions (index, show, new, create, edit)

defmodule MyAppWeb.UserController do
  @moduledoc """
  Phoenix controller for User resource.
  Tests parsing of common Phoenix patterns like action functions,
  pattern matching in function heads, and plug usage.
  """

  use MyAppWeb, :controller

  alias MyApp.Accounts
  alias MyApp.Accounts.User

  # Plug for authentication
  plug :authenticate_user when action in [:edit, :update, :delete]

  # Index action - list all users
  def index(conn, _params) do
    users = Accounts.list_users()
    render(conn, :index, users: users)
  end

  # Show action - display single user with pattern matching
  def show(conn, %{"id" => id}) do
    user = Accounts.get_user!(id)
    render(conn, :show, user: user)
  end

  # New action - render form
  def new(conn, _params) do
    changeset = Accounts.change_user(%User{})
    render(conn, :new, changeset: changeset)
  end

  # Create action - handle form submission
  def create(conn, %{"user" => user_params}) do
    case Accounts.create_user(user_params) do
      {:ok, user} ->
        conn
        |> put_flash(:info, "User created successfully.")
        |> redirect(to: ~p"/users/#{user.id}")

      {:error, %Ecto.Changeset{} = changeset} ->
        render(conn, :new, changeset: changeset)
    end
  end

  # Edit action - render edit form
  def edit(conn, %{"id" => id}) do
    user = Accounts.get_user!(id)
    changeset = Accounts.change_user(user)
    render(conn, :edit, user: user, changeset: changeset)
  end

  # Update action - handle edit form submission
  def update(conn, %{"id" => id, "user" => user_params}) do
    user = Accounts.get_user!(id)

    case Accounts.update_user(user, user_params) do
      {:ok, user} ->
        conn
        |> put_flash(:info, "User updated successfully.")
        |> redirect(to: ~p"/users/#{user.id}")

      {:error, %Ecto.Changeset{} = changeset} ->
        render(conn, :edit, user: user, changeset: changeset)
    end
  end

  # Delete action
  def delete(conn, %{"id" => id}) do
    user = Accounts.get_user!(id)
    {:ok, _user} = Accounts.delete_user(user)

    conn
    |> put_flash(:info, "User deleted successfully.")
    |> redirect(to: ~p"/users")
  end

  defp authenticate_user(conn, _opts) do
    if conn.assigns[:current_user] do
      conn
    else
      conn
      |> put_flash(:error, "You must be logged in.")
      |> redirect(to: ~p"/login")
      |> halt()
    end
  end
end
