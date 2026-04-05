defmodule Mana.Skills.PromptBuilder do
  @moduledoc "Builds skill-related prompt sections"

  @doc "Build available_skills XML for system prompt"
  @spec build_available_skills_xml([map()]) :: String.t()
  def build_available_skills_xml(skills) do
    skill_entries =
      Enum.map_join(skills, "\n", fn skill ->
        """
          <skill>
            <name>#{escape_xml(skill.name)}</name>
            <description>#{escape_xml(skill.description)}</description>
          </skill>
        """
      end)

    """
    <available_skills>
    #{skill_entries}
    </available_skills>
    """
  end

  @doc "Build guidance text for using skills"
  def build_skills_guidance do
    """
    When <available_skill> tags are present, skills can be activated by reading their SKILL.md files.
    Use the activate_skill tool to activate a skill before following its guidance.
    """
  end

  defp escape_xml(text) do
    text
    |> String.replace("&", "&amp;")
    |> String.replace("<", "&lt;")
    |> String.replace(">", "&gt;")
  end
end
