defmodule Mana.Plugins.AgentSkills do
  @moduledoc """
  Agent Skills plugin — hot-loadable domain expertise via load_prompt hook.

  This plugin wires the Mana Skills system into the plugin lifecycle:
  - Discovers SKILL.md files from ~/.mana/skills/, ./skills/, and priv/skills/
  - Tracks active skills per session
  - Injects active skill content into system prompts via :load_prompt
  - Provides /skills command for listing and activating skills

  ## Usage

      /skills list              - Show all available skills
      /skills active            - Show currently active skills
      /skills activate <name>   - Activate a skill for this session
      /skills deactivate <name> - Deactivate a skill
      /skills deactivate --all  - Deactivate all skills

  ## Hooks Registered

  - `:startup` - Load skills into persistent_term
  - `:load_prompt` - Inject active skill content into system prompt
  - `:custom_command` - Handle /skills commands
  - `:agent_run_end` - Clean up session state
  """

  @behaviour Mana.Plugin.Behaviour

  alias Mana.Skills.Loader

  require Logger

  # Persistent term keys
  @available_skills_key {__MODULE__, :available_skills}
  @active_skills_key_prefix {__MODULE__, :active_skills}

  @impl true
  def name, do: "agent_skills"

  @impl true
  def init(_config) do
    # Load available skills on plugin initialization
    load_skills()
    {:ok, %{loaded: true}}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.on_startup/0},
      {:load_prompt, &__MODULE__.on_load_prompt/0},
      {:custom_command, &__MODULE__.on_custom_command/2},
      {:agent_run_end, &__MODULE__.on_agent_run_end/7}
    ]
  end

  @impl true
  def terminate do
    :persistent_term.erase(@available_skills_key)
    # Note: We don't erase active skills here as they are session-scoped
    :ok
  end

  @doc """
  Startup hook - reloads skills from disk.
  """
  def on_startup do
    load_skills()
    :ok
  end

  @doc """
  Load prompt hook - returns content from active skills.
  Called during prompt assembly to inject skill content.
  """
  def on_load_prompt do
    session_id = get_current_session_id()
    active_skills = get_active_skills(session_id)

    if active_skills == [] do
      nil
    else
      build_active_skills_prompt(active_skills)
    end
  end

  @doc """
  Custom command handler for /skills commands.
  """
  def on_custom_command("skills", ["list"]) do
    list_available_skills()
  end

  def on_custom_command("skills", ["active"]) do
    list_active_skills()
  end

  def on_custom_command("skills", ["activate", name]) do
    activate_skill(name)
  end

  def on_custom_command("skills", ["deactivate", "--all"]) do
    deactivate_all_skills()
  end

  def on_custom_command("skills", ["deactivate", name]) do
    deactivate_skill(name)
  end

  def on_custom_command("skills", args) when length(args) >= 2 do
    # Handle activate/deactivate with multi-word names
    [cmd | rest] = args

    case cmd do
      "activate" ->
        name = Enum.join(rest, " ")
        activate_skill(name)

      "deactivate" ->
        name = Enum.join(rest, " ")
        deactivate_skill(name)

      _ ->
        skills_help_text()
    end
  end

  def on_custom_command("skills", _) do
    skills_help_text()
  end

  def on_custom_command(_, _), do: nil

  @doc """
  Agent run end hook - can be used for session cleanup if needed.
  """
  def on_agent_run_end(_agent_name, _model_name, _session_id, _success, _error, _response, _meta) do
    # Skills persist across runs in a session by design
    # Could add session cleanup here if needed
    :ok
  end

  # Public API for skill management

  @doc """
  Returns the list of all available skills.
  """
  @spec list_skills() :: [map()]
  def list_skills do
    :persistent_term.get(@available_skills_key, [])
  end

  @doc """
  Returns the list of active skills for the current session.
  """
  @spec get_active_skills(String.t() | nil) :: [map()]
  def get_active_skills(session_id \\ nil) do
    key = active_skills_key(session_id)
    :persistent_term.get(key, [])
  end

  @doc """
  Activates a skill by name for the current session.
  """
  @spec activate_skill(String.t()) :: String.t()
  def activate_skill(name) do
    session_id = get_current_session_id()

    case find_skill(name) do
      nil ->
        "Skill not found: #{name}\nRun '/skills list' to see available skills."

      skill ->
        current_active = get_active_skills(session_id)

        if skill.name in Enum.map(current_active, & &1.name) do
          "Skill '#{skill.name}' is already active."
        else
          new_active = [skill | current_active]
          set_active_skills(session_id, new_active)
          "Activated skill: #{skill.name}\n#{skill.description}"
        end
    end
  end

  @doc """
  Deactivates a skill by name for the current session.
  """
  @spec deactivate_skill(String.t()) :: String.t()
  def deactivate_skill(name) do
    session_id = get_current_session_id()
    current_active = get_active_skills(session_id)

    case Enum.find(current_active, fn s -> s.name == name end) do
      nil ->
        "Skill '#{name}' is not currently active."

      _skill ->
        new_active = Enum.reject(current_active, fn s -> s.name == name end)
        set_active_skills(session_id, new_active)
        "Deactivated skill: #{name}"
    end
  end

  @doc """
  Deactivates all skills for the current session.
  """
  @spec deactivate_all_skills() :: String.t()
  def deactivate_all_skills do
    session_id = get_current_session_id()
    count = length(get_active_skills(session_id))
    clear_active_skills(session_id)
    "Deactivated #{count} skill(s)."
  end

  # Private functions

  defp load_skills do
    skills = Loader.load()
    :persistent_term.put(@available_skills_key, skills)

    if skills != [] do
      Logger.info("AgentSkills: loaded #{length(skills)} skill(s)")
    end

    skills
  end

  defp find_skill(name) do
    list_skills()
    |> Enum.find(fn s -> s.name == name end)
  end

  defp build_active_skills_prompt(active_skills) do
    header = "## Active Skills\n\nThe following skills are currently active:\n"

    skills_content =
      Enum.map_join(active_skills, "\n\n", fn skill ->
        """
        ### #{skill.name}
        #{skill.description}

        #{skill.content}
        """
      end)

    "#{header}\n#{skills_content}"
  end

  defp list_available_skills do
    skills = list_skills()

    if skills == [] do
      """
      No skills available.

      Skills are loaded from:
        - ~/.mana/skills/*.md
        - ./skills/*.md
        - priv/skills/*.md (built-in)

      Create a SKILL.md file with YAML frontmatter:
        ---
        name: my-skill
        description: What this skill does
        ---

        Skill content here...
      """
    else
      header = "Available skills:\n\n"

      skill_lines = Enum.map(skills, &format_skill_line/1)

      footer = "\n\nUse '/skills activate <name>' to activate a skill."

      header <> Enum.join(skill_lines, "\n\n") <> footer
    end
  end

  defp list_active_skills do
    session_id = get_current_session_id()
    active = get_active_skills(session_id)

    if active == [] do
      "No skills currently active.\n\nUse '/skills list' to see available skills."
    else
      header = "Active skills:\n\n"

      skill_lines =
        Enum.map(active, fn skill ->
          "  • #{skill.name}\n    #{skill.description}"
        end)

      footer = "\n\nThese skills are included in your system prompt."

      header <> Enum.join(skill_lines, "\n\n") <> footer
    end
  end

  defp skills_help_text do
    """
    Usage: /skills <command>

    Commands:
      list                    - Show all available skills
      active                  - Show currently active skills
      activate <name>         - Activate a skill for this session
      deactivate <name>       - Deactivate a skill
      deactivate --all        - Deactivate all skills

    Examples:
      /skills activate elixir-dev
      /skills deactivate rust-api
    """
  end

  # Session management helpers

  defp get_current_session_id do
    # Try to get from process dictionary first (set by agent runner)
    Process.get(:mana_session_id) ||
      # Fall back to "default" for non-session contexts
      "default"
  end

  defp active_skills_key(nil), do: {@active_skills_key_prefix, "default"}
  defp active_skills_key(session_id), do: {@active_skills_key_prefix, session_id}

  defp set_active_skills(session_id, skills) do
    key = active_skills_key(session_id)
    :persistent_term.put(key, skills)
  end

  defp clear_active_skills(session_id) do
    key = active_skills_key(session_id)
    :persistent_term.erase(key)
  end

  defp format_skill_line(skill) do
    tags_str = format_tags(skill.tags)
    "  • #{skill.name}#{tags_str}\n    #{skill.description}"
  end

  defp format_tags([]), do: ""
  defp format_tags(tags), do: " [#{Enum.join(tags, ", ")}]"
end
