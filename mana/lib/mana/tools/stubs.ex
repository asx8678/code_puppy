defmodule Mana.Tools.Stubs do
  @moduledoc """
  Stub tool implementations for Phase 1.

  These tools return `{:error, :not_implemented}` but provide
  the correct schema definitions for agent configuration.
  """

  alias Mana.Tools.Behaviour

  defmodule ListFiles do
    @moduledoc "Stub tool for listing files"
    @behaviour Behaviour

    @impl true
    def name, do: "list_files"

    @impl true
    def description, do: "List files in a directory"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          path: %{
            type: "string",
            description: "Directory path to list"
          },
          recursive: %{
            type: "boolean",
            description: "List recursively",
            default: false
          }
        },
        required: ["path"]
      }
    end

    @impl true
    def execute(_args) do
      {:error, :not_implemented}
    end
  end

  defmodule ReadFile do
    @moduledoc "Stub tool for reading files"
    @behaviour Behaviour

    @impl true
    def name, do: "read_file"

    @impl true
    def description, do: "Read contents of a file"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          path: %{
            type: "string",
            description: "Path to the file"
          },
          start_line: %{
            type: "integer",
            description: "Starting line number (1-indexed)"
          },
          num_lines: %{
            type: "integer",
            description: "Number of lines to read"
          }
        },
        required: ["path"]
      }
    end

    @impl true
    def execute(_args) do
      {:error, :not_implemented}
    end
  end

  defmodule WriteFile do
    @moduledoc "Stub tool for writing files"
    @behaviour Behaviour

    @impl true
    def name, do: "write_file"

    @impl true
    def description, do: "Write content to a file"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          path: %{
            type: "string",
            description: "Path to the file"
          },
          content: %{
            type: "string",
            description: "Content to write"
          }
        },
        required: ["path", "content"]
      }
    end

    @impl true
    def execute(_args) do
      {:error, :not_implemented}
    end
  end

  defmodule EditFile do
    @moduledoc "Stub tool for editing files"
    @behaviour Behaviour

    @impl true
    def name, do: "edit_file"

    @impl true
    def description, do: "Edit an existing file"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          path: %{
            type: "string",
            description: "Path to the file"
          },
          old_str: %{
            type: "string",
            description: "Text to replace"
          },
          new_str: %{
            type: "string",
            description: "Replacement text"
          }
        },
        required: ["path", "old_str", "new_str"]
      }
    end

    @impl true
    def execute(_args) do
      {:error, :not_implemented}
    end
  end

  defmodule RunShellCommand do
    @moduledoc "Stub tool for running shell commands"
    @behaviour Behaviour

    @impl true
    def name, do: "run_shell_command"

    @impl true
    def description, do: "Execute a shell command"

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          command: %{
            type: "string",
            description: "Command to execute"
          },
          cwd: %{
            type: "string",
            description: "Working directory for command execution"
          },
          timeout: %{
            type: "integer",
            description: "Timeout in seconds",
            default: 60
          }
        },
        required: ["command"]
      }
    end

    @impl true
    def execute(_args) do
      {:error, :not_implemented}
    end
  end
end
