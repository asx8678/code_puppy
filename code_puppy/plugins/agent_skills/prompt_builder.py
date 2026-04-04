"""Build available_skills XML for system prompt injection."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .metadata import SkillMetadata


def build_available_skills_xml(skills: list["SkillMetadata"], condensed: bool = False, max_skills: int = 20) -> str:
    """Build Claude-optimized XML listing available skills.

    Args:
        skills: List of SkillMetadata objects to include in the XML.
        condensed: Whether to use condensed mode (shorter descriptions).
        max_skills: Maximum number of skills to include in condensed mode.

    Returns:
        XML string listing available skills in the format:
        <available_skills>
          <skill>
            <name>skill-name</name>
            <description>What the skill does...</description>
          </skill>
          ...
        </available_skills>

    To use a skill, call activate_skill(skill_name) to load full instructions.
    """
    if not skills:
        return "<available_skills></available_skills>"

    # In condensed mode, limit number of skills
    if condensed and len(skills) > max_skills:
        skills = skills[:max_skills]
        truncated = True
    else:
        truncated = False

    xml_parts = ["<available_skills>"]

    for skill in skills:
        xml_parts.append("  <skill>")
        xml_parts.append(f"    <name>{skill.name}</name>")
        if skill.description:
            # Escape any XML special characters in the description
            escaped_desc = (
                skill.description.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;")
            )
            # In condensed mode, truncate long descriptions
            if condensed and len(escaped_desc) > 100:
                escaped_desc = escaped_desc[:97] + "..."
            xml_parts.append(f"    <description>{escaped_desc}</description>")
        xml_parts.append("  </skill>")

    if truncated:
        xml_parts.append("  <!-- More skills available. Use list_or_search_skills() to see all. -->")

    xml_parts.append("</available_skills>")

    return "\n".join(xml_parts)


def build_skills_guidance(condensed: bool = False) -> str:
    """Return guidance text for how to use skills.
    
    Args:
        condensed: Whether to use condensed mode (shorter guidance).
    """
    if condensed:
        return """
# Agent Skills

Match tasks to skill descriptions. Call `activate_skill(skill_name)` to load instructions.
"""
    return """
# Agent Skills

When `<available_skills>` appears in context, match user tasks to skill descriptions.
Call `activate_skill(skill_name)` to load full instructions before starting the task.
Use `list_or_search_skills(query)` to search for relevant skills.
"""
