defmodule CodePuppyControl.Tools.FileModifications.Permissions do
  @moduledoc """
  Permission handling and user rejection responses for file modifications.

  Port of `code_puppy/tools/file_modifications.py:_create_rejection_response`.

  Creates standardized rejection responses when the user (or policy engine)
  explicitly denies a file operation. Integrates with the `PolicyEngine`
  for security-sensitive operations.

  ## Design

  - All operations go through `permission_check/2` before execution
  - Rejection responses include user feedback when available
  - Policy engine can deny operations based on path sensitivity
  - User rejection is final — no retries allowed
  """

  alias CodePuppyControl.FileOps.Security

  @doc """
  Create a standardized rejection response with user feedback if available.

  Matches the Python `_create_rejection_response` contract.

  ## Examples

      iex> Permissions.create_rejection_response("/tmp/test.txt")
      %{success: false, path: "/tmp/test.txt", message: "USER REJECTED: ...", changed: false, user_rejection: true}
  """
  @spec create_rejection_response(Path.t(), String.t() | nil) :: map()
  def create_rejection_response(file_path, user_feedback \\ nil) do
    base_message = "USER REJECTED: The user explicitly rejected these file changes."

    message =
      if user_feedback && user_feedback != "" do
        "#{base_message} User feedback: #{user_feedback}"
      else
        "#{base_message} Please do not retry the same changes or any other changes - immediately ask for clarification."
      end

    %{
      success: false,
      path: file_path,
      message: message,
      changed: false,
      user_rejection: true,
      rejection_type: "explicit_user_denial",
      user_feedback: user_feedback
    }
  end

  @doc """
  Create an error response for a denied operation.

  Used when the policy engine denies an operation (not user rejection).
  """
  @spec create_denial_response(Path.t(), String.t()) :: map()
  def create_denial_response(file_path, reason) do
    %{
      success: false,
      path: file_path,
      message: "Operation denied: #{reason}",
      changed: false,
      user_rejection: false,
      rejection_type: "policy_denial"
    }
  end

  @doc """
  Create an error response for a security-blocked operation.

  Used when `FileOps.Security` blocks access to a sensitive path.
  """
  @spec create_security_response(Path.t(), String.t()) :: map()
  def create_security_response(file_path, reason) do
    %{
      success: false,
      path: file_path,
      message: "Security: #{reason}",
      changed: false,
      user_rejection: false,
      rejection_type: "security_block"
    }
  end

  @doc """
  Check file permission for a given operation.

  Combines security path validation with policy engine checks.
  Returns `:ok` if allowed, `{:deny, reason}` if denied.

  ## Examples

      iex> Permissions.check_permission("/tmp/test.txt", "create")
      :ok

      iex> Permissions.check_permission(Path.join(System.user_home!(), ".ssh/id_rsa"), "read")
      {:deny, "Access to sensitive path blocked"}
  """
  @spec check_permission(Path.t(), String.t()) :: :ok | {:deny, String.t()}
  def check_permission(file_path, operation) do
    case Security.validate_path(file_path, operation) do
      {:ok, _} -> :ok
      {:error, reason} -> {:deny, reason}
    end
  end

  @doc """
  Wrap an operation with permission check.

  If the permission check passes, executes the function.
  If denied, returns a rejection response immediately.

  ## Examples

      iex> Permissions.with_permission("/tmp/test.txt", "create", fn -> {:ok, %{success: true}} end)
      {:ok, %{success: true}}
  """
  @spec with_permission(Path.t(), String.t(), (-> {:ok, map()} | {:error, map()})) ::
          {:ok, map()} | {:error, map()}
  def with_permission(file_path, operation, fun) do
    case check_permission(file_path, operation) do
      :ok ->
        fun.()

      {:deny, reason} ->
        {:error, create_security_response(file_path, reason)}
    end
  end
end
