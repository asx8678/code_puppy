defmodule Mana.Pack.Agent do
  @moduledoc """
  Behaviour module defining the contract for Pack agents.

  Pack agents are specialized modules that implement the pack workflow
  for managing development tasks using the local issue tracker (bd).

  Each agent has a specific role:
  - `Bloodhound`: Issue tracking specialist
  - `Terrier`: Worktree management specialist
  - `Husky`: Task execution specialist
  - `Shepherd`: Code review critic
  - `Watchdog`: QA critic
  - `Retriever`: Branch merge specialist

  ## Usage

  To implement the behaviour:

      defmodule Mana.Pack.Agents.MyAgent do
        @behaviour Mana.Pack.Agent

        @impl true
        def name, do: "MyAgent 🐾"

        @impl true
        def execute(task, opts) do
          # Implementation
          {:ok, result}
        end
      end
  """

  @typedoc "Task specification for Pack agents"
  @type task :: %{
          id: String.t(),
          issue_id: String.t() | nil,
          worktree: String.t() | nil,
          description: String.t(),
          metadata: map()
        }

  @typedoc "Execution options"
  @type opts :: keyword()

  @typedoc "Execution result"
  @type result :: term()

  @typedoc "Execution error reason"
  @type reason :: term()

  @doc """
  Executes the agent's primary task.

  ## Parameters

    - `task`: A map containing task details including:
      - `:id` - Unique task identifier
      - `:issue_id` - Optional issue reference (e.g., "bd-42")
      - `:worktree` - Optional worktree path
      - `:description` - Task description
      - `:metadata` - Additional task metadata

    - `opts`: Keyword list of execution options:
      - `:timeout` - Maximum execution time in milliseconds
      - `:cwd` - Current working directory
      - `:env` - Environment variables
      - Other agent-specific options

  ## Returns

    - `{:ok, result}` - Successful execution with the result
    - `{:error, reason}` - Failed execution with error details
  """
  @callback execute(task :: task(), opts :: opts()) ::
              {:ok, result :: result()} | {:error, reason :: reason()}

  @doc """
  Returns the agent's display name.

  Used for logging, status reporting, and workflow coordination.

  ## Examples

      iex> Mana.Pack.Agents.Bloodhound.name()
      "Bloodhound 🐕‍🦺"
  """
  @callback name() :: String.t()

  @doc """
  Gets a value from metadata by key, supporting both atom and string keys.

  Returns `metadata[key]` if present, otherwise falls back to `metadata[Atom.to_string(key)]`.

  ## Examples

      iex> metadata = %{"command" => "ready", args: ["--json"]}
      iex> Mana.Pack.Agent.get_meta(metadata, :command)
      "ready"

      iex> Mana.Pack.Agent.get_meta(metadata, :args)
      ["--json"]
  """
  @spec get_meta(map(), atom()) :: term()
  def get_meta(metadata, key) when is_atom(key) do
    metadata[key] || metadata[Atom.to_string(key)]
  end
end
