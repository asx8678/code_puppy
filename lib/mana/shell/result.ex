defmodule Mana.Shell.Result do
  @moduledoc "Shell command execution result"

  defstruct [
    :success,
    :command,
    :stdout,
    :stderr,
    :exit_code,
    :execution_time,
    :timeout?,
    :user_interrupted?
  ]

  @type t :: %__MODULE__{
          success: boolean(),
          command: String.t(),
          stdout: String.t(),
          stderr: String.t(),
          exit_code: integer(),
          execution_time: integer(),
          timeout?: boolean(),
          user_interrupted?: boolean()
        }
end
