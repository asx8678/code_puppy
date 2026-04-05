defmodule Mana.Skills do
  @moduledoc "Agent Skills System — hot-loadable domain expertise"
  @behaviour Mana.Plugin.Behaviour

  alias Mana.Skills.Loader
  alias Mana.Skills.PromptBuilder

  require Logger

  @impl true
  def name, do: "skills"

  @impl true
  def init(_config) do
    load_skills()
    {:ok, %{loaded: true}}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.on_startup/0},
      {:get_model_system_prompt, &__MODULE__.on_get_model_system_prompt/3},
      {:register_tools, &__MODULE__.on_register_tools/0},
      {:custom_command, &__MODULE__.on_custom_command/2}
    ]
  end

  @impl true
  def terminate do
    :persistent_term.erase({__MODULE__, :skills})
    :ok
  end

  @doc false
  def on_startup do
    load_skills()
    :ok
  end

  @doc false
  def on_get_model_system_prompt(_model_name, _default_prompt, _user_prompt) do
    skills = :persistent_term.get({__MODULE__, :skills}, [])

    if skills == [] do
      nil
    else
      catalog = PromptBuilder.build_available_skills_xml(skills)
      guidance = PromptBuilder.build_skills_guidance()
      %{instructions: "#{catalog}\n#{guidance}", handled: true}
    end
  end

  @doc false
  def on_register_tools do
    [
      %{
        name: "activate_skill",
        description: "Activate a skill by reading its content",
        parameters: %{
          type: "object",
          properties: %{
            name: %{
              type: "string",
              description: "Skill name"
            }
          },
          required: ["name"]
        },
        execute: fn %{"name" => name} ->
          case find_skill(name) do
            nil -> {:error, "Skill not found: #{name}"}
            skill -> {:ok, %{"activated" => skill.name, "content" => skill.content}}
          end
        end
      },
      %{
        name: "list_or_search_skills",
        description: "List all skills or search by keyword",
        parameters: %{
          type: "object",
          properties: %{
            query: %{
              type: "string",
              description: "Search query (optional)"
            }
          }
        },
        execute: fn args ->
          skills = :persistent_term.get({__MODULE__, :skills}, [])
          query = Map.get(args, "query")

          results =
            if query do
              Enum.filter(skills, fn s ->
                String.contains?(String.downcase(s.name), String.downcase(query)) or
                  String.contains?(String.downcase(s.description), String.downcase(query))
              end)
            else
              skills
            end

          {:ok, %{"skills" => Enum.map(results, &%{name: &1.name, description: &1.description})}}
        end
      }
    ]
  end

  @doc false
  def on_custom_command("skills", ["list"]) do
    :persistent_term.get({__MODULE__, :skills}, [])
    |> format_skill_list()
  end

  def on_custom_command("skills", ["search", query]) do
    :persistent_term.get({__MODULE__, :skills}, [])
    |> search_skills(query)
    |> format_search_results(query)
  end

  def on_custom_command("skills", _) do
    """
    Usage:
      /skills list              - List all available skills
      /skills search <query>    - Search skills by keyword
    """
  end

  def on_custom_command(_, _), do: nil

  # Private functions

  defp load_skills do
    skills = Loader.load()
    :persistent_term.put({__MODULE__, :skills}, skills)

    if skills != [] do
      Logger.info("Skills: loaded #{length(skills)} skill(s)")
    end

    skills
  end

  defp find_skill(name) do
    skills = :persistent_term.get({__MODULE__, :skills}, [])
    Enum.find(skills, fn s -> s.name == name end)
  end

  defp format_skill_list([]), do: "No skills loaded."

  defp format_skill_list(skills) do
    header = "Available skills:\n\n"
    skill_lines = Enum.map(skills, &format_skill_line/1)
    header <> Enum.join(skill_lines, "\n\n")
  end

  defp format_skill_line(skill) do
    tags_str =
      if skill.tags == [],
        do: "",
        else: " [#{Enum.join(skill.tags, ", ")}]"

    "  • #{skill.name}#{tags_str}\n    #{skill.description}"
  end

  defp search_skills(skills, query) do
    Enum.filter(skills, fn s ->
      String.contains?(String.downcase(s.name), String.downcase(query)) or
        String.contains?(String.downcase(s.description), String.downcase(query))
    end)
  end

  defp format_search_results([], query), do: "No skills found matching '#{query}'."

  defp format_search_results(results, _query) do
    header = "Matching skills:\n\n"

    skill_lines =
      Enum.map(results, fn skill ->
        "  • #{skill.name}\n    #{skill.description}"
      end)

    header <> Enum.join(skill_lines, "\n\n")
  end
end
