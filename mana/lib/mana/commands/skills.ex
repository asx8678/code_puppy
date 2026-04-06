defmodule Mana.Commands.Skills do
  @moduledoc """
  Skills management command.

  Provides commands for listing, activating, and deactivating agent skills.
  Skills are hot-loadable domain expertise loaded from SKILL.md files.

  ## Commands

  - `/skills` - Show available skills (same as `/skills list`)
  - `/skills list` - List all available skills
  - `/skills active` - Show currently active skills
  - `/skills activate <name>` - Activate a skill for this session
  - `/skills deactivate <name>` - Deactivate a skill
  - `/skills deactivate --all` - Deactivate all skills

  ## Examples

      /skills
      # Shows all available skills

      /skills activate elixir-dev
      # Activates the elixir-dev skill for this session

      /skills deactivate elixir-dev
      # Deactivates the elixir-dev skill
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Plugins.AgentSkills

  @impl true
  def name, do: "/skills"

  @impl true
  def description, do: "List and manage agent skills"

  @impl true
  def usage, do: "/skills [list|active|activate <name>|deactivate <name>|deactivate --all]"

  @impl true
  def execute([], _context) do
    text = AgentSkills.on_custom_command("skills", ["list"])
    {:ok, text}
  end

  def execute(["list"], _context) do
    text = AgentSkills.on_custom_command("skills", ["list"])
    {:ok, text}
  end

  def execute(["active"], _context) do
    text = AgentSkills.on_custom_command("skills", ["active"])
    {:ok, text}
  end

  def execute(["activate" | name_parts], _context) when name_parts != [] do
    name = Enum.join(name_parts, " ")
    text = AgentSkills.activate_skill(name)
    {:ok, text}
  end

  def execute(["deactivate", "--all"], _context) do
    text = AgentSkills.deactivate_all_skills()
    {:ok, text}
  end

  def execute(["deactivate" | name_parts], _context) when name_parts != [] do
    name = Enum.join(name_parts, " ")
    text = AgentSkills.deactivate_skill(name)
    {:ok, text}
  end

  def execute(["activate"], _context) do
    {:error, "Usage: /skills activate <name>"}
  end

  def execute(["deactivate"], _context) do
    {:error, "Usage: /skills deactivate <name>"}
  end

  def execute([unknown | _], _context) do
    {:error, "Unknown subcommand: #{unknown}. #{usage()}"}
  end
end
