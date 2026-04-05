defmodule Mana.Tools.Browser.Workflow do
  @moduledoc """
  Tools for recording, listing, and reading browser workflows.

  Workflows are sequences of browser actions that can be recorded during
  a session and replayed later. They are persisted as JSON files in the
  application's priv directory.

  Provides three operations:
  - **Save workflow**: Save the current recorded action sequence as a named workflow
  - **List workflows**: List all saved workflow names
  - **Read workflow**: Read the steps of a specific saved workflow

  Each operation is a separate Behaviour module.

  ## Examples

      {:ok, %{"name" => "login_flow", "steps" => 5}} =
        Mana.Tools.Browser.Workflow.SaveWorkflow.execute(%{
          "name" => "login_flow",
          "description" => "Standard login sequence"
        })

      {:ok, %{"workflows" => ["login_flow", "search_test"]}} =
        Mana.Tools.Browser.Workflow.ListWorkflows.execute(%{})

      {:ok, %{"steps" => [...]}} =
        Mana.Tools.Browser.Workflow.ReadWorkflow.execute(%{"name" => "login_flow"})
  """

  alias Mana.Tools.Browser.Manager

  # ---------------------------------------------------------------------------
  # Save workflow
  # ---------------------------------------------------------------------------

  defmodule SaveWorkflow do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_save_workflow"

    @impl true
    def description do
      "Save the current browser action sequence as a named workflow for later replay. " <>
        "Captures all browser actions performed since the last workflow save."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          name: %{
            type: "string",
            description: "Unique name for the workflow"
          },
          description: %{
            type: "string",
            description: "Optional human-readable description of what this workflow does"
          }
        },
        required: ["name"]
      }
    end

    @impl true
    def execute(args) do
      name = Map.fetch!(args, "name")
      description = Map.get(args, "description", "")

      params = %{
        "action" => "save",
        "name" => name,
        "description" => description
      }

      case Manager.execute("workflow", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Save workflow failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: name"}
    end
  end

  # ---------------------------------------------------------------------------
  # List workflows
  # ---------------------------------------------------------------------------

  defmodule ListWorkflows do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_list_workflows"

    @impl true
    def description do
      "List all saved browser workflows by name. " <>
        "Returns the workflow names and their descriptions."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{},
        required: []
      }
    end

    @impl true
    def execute(_args) do
      case Manager.execute("workflow", %{"action" => "list"}) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "List workflows failed: #{reason}"}
      end
    end
  end

  # ---------------------------------------------------------------------------
  # Read workflow
  # ---------------------------------------------------------------------------

  defmodule ReadWorkflow do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_read_workflow"

    @impl true
    def description do
      "Read the steps of a saved workflow. Returns the full sequence of " <>
        "browser actions that make up the workflow."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          name: %{
            type: "string",
            description: "The name of the workflow to read"
          }
        },
        required: ["name"]
      }
    end

    @impl true
    def execute(args) do
      name = Map.fetch!(args, "name")

      params = %{
        "action" => "read",
        "name" => name
      }

      case Manager.execute("workflow", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Read workflow failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: name"}
    end
  end
end
