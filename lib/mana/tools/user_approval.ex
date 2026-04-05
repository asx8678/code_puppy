defmodule Mana.Tools.UserApproval do
  @moduledoc """
  User approval flows for file and command operations.

  This module provides thin wrappers around `Mana.MessageBus` for
  requesting user approval before potentially destructive operations.

  ## Usage

      # Request approval for file creation
      Mana.Tools.UserApproval.request_file_approval(:create, %{path: "/tmp/file.txt"})

      # Request approval for command execution
      Mana.Tools.UserApproval.request_command_approval("rm -rf /", "/home/user")

  All approval requests block until the user responds or a timeout occurs.
  """

  alias Mana.MessageBus

  @doc """
  Request user approval for a file operation.

  ## Parameters

    - `operation` - Atom representing the operation (`:create`, `:replace`, `:delete`)
    - `details` - Map with operation details (must include `:path` for most operations)

  ## Returns

    - `{:ok, true}` - User approved the operation
    - `{:ok, false}` - User rejected the operation
    - `{:error, :timeout}` - Request timed out

  ## Examples

      Mana.Tools.UserApproval.request_file_approval(:create, %{path: "/tmp/new_file.ex"})
      # => {:ok, true}

      Mana.Tools.UserApproval.request_file_approval(:delete, %{path: "/tmp/important.txt"})
      # Shows warning: "Delete file: `/tmp/important.txt`? This cannot be undone!"
  """
  @spec request_file_approval(atom(), map()) :: {:ok, boolean()} | {:error, :timeout}
  def request_file_approval(operation, details) do
    message = build_file_message(operation, details)

    MessageBus.request_confirmation(message,
      type: :file_approval,
      operation: operation,
      details: details
    )
  catch
    :exit, {:timeout, _} ->
      {:error, :timeout}
  end

  @doc """
  Request user approval for a command execution.

  ## Parameters

    - `command` - The command string to be executed
    - `cwd` - The working directory where the command will run

  ## Returns

    - `{:ok, true}` - User approved the command execution
    - `{:ok, false}` - User rejected the command execution
    - `{:error, :timeout}` - Request timed out

  ## Examples

      Mana.Tools.UserApproval.request_command_approval("mix test", "/project")
      # => {:ok, true}
  """
  @spec request_command_approval(String.t(), String.t()) :: {:ok, boolean()} | {:error, :timeout}
  def request_command_approval(command, cwd) do
    message = "Execute command: `#{command}` in `#{cwd}`?"

    MessageBus.request_confirmation(message,
      type: :command_approval,
      command: command,
      cwd: cwd
    )
  catch
    :exit, {:timeout, _} ->
      {:error, :timeout}
  end

  # Build the confirmation message for file operations
  defp build_file_message(operation, %{path: path}) do
    case operation do
      :create ->
        "Create file: `#{path}`?"

      :replace ->
        "Modify file: `#{path}`?"

      :delete ->
        "Delete file: `#{path}`? This cannot be undone!"

      :edit ->
        "Edit file: `#{path}`?"

      _ ->
        "#{capitalize_first(Atom.to_string(operation))} file: `#{path}`?"
    end
  end

  defp build_file_message(operation, _) do
    "#{capitalize_first(Atom.to_string(operation))} file?"
  end

  defp capitalize_first(string) do
    string
    |> String.first()
    |> String.upcase()
    |> Kernel.<>(String.slice(string, 1..-1//1))
  end
end
