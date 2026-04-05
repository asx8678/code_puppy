defmodule Mana.Plugins.UniversalConstructor.Plugin do
  @moduledoc """
  Plugin registration for the Universal Constructor.

  Implements `Mana.Plugin.Behaviour` to integrate UC into Mana.
  Registers a `universal_constructor` tool (via `register_tools` hook)
  and a `/uc` custom command for interactive CLI usage.

  ## Tool Usage

      %{"action" => "create_agent", "name" => "...", "description" => "...", "system_prompt" => "..."}
      %{"action" => "create_tool", "name" => "...", "description" => "..."}
      %{"action" => "list"}
      %{"action" => "delete", "name" => "...", "type" => "agent" | "tool"}

  ## Command Usage

      /uc list | /uc create agent <name> <desc> | /uc delete <type> <name>
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  alias Mana.Plugins.UniversalConstructor.Engine

  # ---------------------------------------------------------------------------
  # Plugin.Behaviour
  # ---------------------------------------------------------------------------

  @impl Mana.Plugin.Behaviour
  def name, do: "universal_constructor"

  @impl Mana.Plugin.Behaviour
  def init(_config) do
    dir = Mana.Plugins.UniversalConstructor.Template.user_tools_dir()
    File.mkdir_p(dir)
    Logger.info("[UC] Universal Constructor plugin initialized, tools dir: #{dir}")
    {:ok, %{tools_dir: dir}}
  end

  @impl Mana.Plugin.Behaviour
  def hooks do
    [
      {:register_tools, &__MODULE__.on_register_tools/0},
      {:custom_command, &__MODULE__.handle_custom_command/2},
      {:custom_command_help, &__MODULE__.command_help/0}
    ]
  end

  @impl Mana.Plugin.Behaviour
  def terminate, do: :ok

  # ---------------------------------------------------------------------------
  # register_tools hook
  # ---------------------------------------------------------------------------

  @doc false
  def on_register_tools do
    [
      %{
        name: "universal_constructor",
        description:
          "Create, list, or delete agents and tools at runtime. Actions: create_agent, create_tool, list, delete.",
        parameters: tool_parameters(),
        execute: &execute_uc/1
      }
    ]
  end

  defp tool_parameters do
    %{
      type: "object",
      properties: %{
        action: %{
          type: "string",
          description: "Operation: create_agent, create_tool, list, or delete",
          enum: ["create_agent", "create_tool", "list", "delete"]
        },
        name: %{type: "string", description: "Name for the agent or tool (required for create/delete)"},
        description: %{type: "string", description: "Description (required for create actions)"},
        system_prompt: %{type: "string", description: "System prompt for the agent (create_agent only)"},
        parameters: %{type: "object", description: "JSON Schema properties for tool parameters (create_tool only)"},
        type: %{type: "string", description: "Artifact type for delete: 'agent' or 'tool'", enum: ["agent", "tool"]}
      },
      required: ["action"]
    }
  end

  # ---------------------------------------------------------------------------
  # Tool execution
  # ---------------------------------------------------------------------------

  def execute_uc(%{"action" => "create_agent"} = args) do
    spec = Map.take(args, ["name", "description", "system_prompt", "display_name", "available_tools"])

    case Engine.create_agent(spec) do
      {:ok, path} -> {:ok, "Agent created: #{spec["name"]} at #{path}"}
      {:error, reason} -> {:error, reason}
    end
  end

  def execute_uc(%{"action" => "create_tool"} = args) do
    spec = Map.take(args, ["name", "description", "parameters", "execute_body", "module_name"])

    case Engine.create_tool(spec) do
      {:ok, path} -> {:ok, "Tool created: #{spec["name"]} at #{path}"}
      {:error, reason} -> {:error, reason}
    end
  end

  def execute_uc(%{"action" => "list"}) do
    %{agents: agents, tools: tools} = Engine.list_creations()

    lines =
      Enum.map(agents, &"  agent: #{&1.name} (#{&1.path})") ++
        Enum.map(tools, &"  tool: #{&1.name} (#{&1.path})")

    {:ok,
     if(lines == [], do: "No UC-created agents or tools found.", else: "UC Creations:\n" <> Enum.join(lines, "\n"))}
  end

  def execute_uc(%{"action" => "delete", "name" => name, "type" => type}) do
    type_atom = if type == "agent", do: :agent, else: :tool

    case Engine.delete_creation(name, type_atom) do
      :ok -> {:ok, "#{String.capitalize(type)} deleted: #{name}"}
      {:error, reason} -> {:error, reason}
    end
  end

  def execute_uc(%{"action" => action}),
    do: {:error, "Unknown or incomplete action: #{action}. Missing required fields?"}

  def execute_uc(_), do: {:error, "Missing required 'action' field."}

  # ---------------------------------------------------------------------------
  # /uc custom command
  # ---------------------------------------------------------------------------

  @doc false
  def handle_custom_command("uc", args) do
    case args do
      ["list" | _] ->
        %{agents: agents, tools: tools} = Engine.list_creations()
        lines = Enum.map(agents, &"  agent: #{&1.name}") ++ Enum.map(tools, &"  tool: #{&1.name}")
        {:ok, if(lines == [], do: "No UC creations yet.", else: "UC Creations:\n" <> Enum.join(lines, "\n"))}

      ["create", "agent", name | rest] ->
        desc = Enum.join(rest, " ")

        case Engine.create_agent(%{
               "name" => name,
               "description" => desc,
               "system_prompt" => "You are #{name}. #{desc}"
             }) do
          {:ok, path} -> {:ok, "Agent created at #{path}"}
          {:error, reason} -> {:ok, "Error: #{reason}"}
        end

      ["create", "tool", name | rest] ->
        desc = Enum.join(rest, " ")

        case Engine.create_tool(%{"name" => name, "description" => desc}) do
          {:ok, path} -> {:ok, "Tool created at #{path}"}
          {:error, reason} -> {:ok, "Error: #{reason}"}
        end

      ["delete", type, name] when type in ["agent", "tool"] ->
        type_atom = if type == "agent", do: :agent, else: :tool

        case Engine.delete_creation(name, type_atom) do
          :ok -> {:ok, "#{String.capitalize(type)} deleted: #{name}"}
          {:error, reason} -> {:ok, "Error: #{reason}"}
        end

      _ ->
        {:ok,
         "Usage: /uc list | /uc create agent <name> <desc> | /uc create tool <name> <desc> | /uc delete <type> <name>"}
    end
  end

  def handle_custom_command(_command, _args), do: nil

  @doc false
  def command_help do
    [
      {"uc",
       "Universal Constructor: list | create agent <name> <desc> | create tool <name> <desc> | delete <type> <name>"}
    ]
  end
end
