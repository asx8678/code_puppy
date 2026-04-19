defmodule CodePuppyControl.Tools.Skills do
  @moduledoc """
  Skills tools — dedicated tools for Agent Skills integration.

  Provides two tools:

  - `list_skills` — List available skills, optionally filtered by search query
  - `activate_skill` — Activate a skill by loading its full SKILL.md instructions

  Skills are discovered from configured skill directories (typically
  `~/.code_puppy/skills/` and `./skills/`). Each skill must have a SKILL.md file.

  ## Design

  This is a lightweight port — it scans the filesystem for SKILL.md files
  and returns their metadata. The full Python skill system (plugins, discovery,
  metadata parsing) is out of scope for this port.
  """

  require Logger

  alias CodePuppyControl.Tool.Registry

  defmodule ListSkills do
    @moduledoc "List available skills, optionally filtered by search query."

    use CodePuppyControl.Tool

    @impl true
    def name, do: :list_skills

    @impl true
    def description do
      "List available skills, optionally filtered by search query. " <>
        "Returns skill names, descriptions, paths, and tags."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "query" => %{
            "type" => "string",
            "description" =>
              "Optional search term to filter skills by name/description/tags. " <>
                "If omitted, returns all available skills."
          }
        },
        "required" => []
      }
    end

    @impl true
    def invoke(args, _context) do
      query = Map.get(args, "query")
      skill_dirs = get_skill_dirs()

      skills =
        skill_dirs
        |> discover_skills()
        |> filter_skills(query)

      {:ok,
       %{
         skills: skills,
         total_count: length(skills),
         query: query
       }}
    end

    defp get_skill_dirs do
      home_dir = System.user_home!()
      project_dir = File.cwd!()

      [Path.join(home_dir, ".code_puppy/skills"), Path.join(project_dir, "skills")]
      |> Enum.filter(&File.dir?/1)
    end

    defp discover_skills(dirs) do
      Enum.flat_map(dirs, fn dir ->
        case File.ls(dir) do
          {:ok, entries} ->
            Enum.flat_map(entries, fn entry ->
              skill_dir = Path.join(dir, entry)
              skill_md = Path.join(skill_dir, "SKILL.md")

              if File.dir?(skill_dir) and File.exists?(skill_md) do
                metadata = parse_skill_metadata(skill_dir, skill_md)
                [metadata]
              else
                []
              end
            end)

          {:error, _} ->
            []
        end
      end)
    end

    defp parse_skill_metadata(skill_dir, skill_md) do
      case File.read(skill_md) do
        {:ok, content} ->
          %{
            name: Path.basename(skill_dir),
            description: extract_description(content),
            path: skill_dir,
            tags: extract_tags(content)
          }

        {:error, _} ->
          %{name: Path.basename(skill_dir), description: "", path: skill_dir, tags: []}
      end
    end

    defp extract_description(content) do
      content
      |> String.split("\n")
      |> Enum.drop_while(&(&1 == ""))
      |> Enum.take_while(&(not String.starts_with?(&1, "#")))
      |> Enum.join(" ")
      |> String.trim()
      |> String.slice(0, 200)
    end

    defp extract_tags(content) do
      case Regex.run(~r/tags:\s*\[(.*?)\]/, content) do
        [_, tags_str] ->
          tags_str
          |> String.split(",")
          |> Enum.map(&String.trim/1)
          |> Enum.map(&String.trim(&1, "\""))
          |> Enum.reject(&(&1 == ""))

        _ ->
          []
      end
    end

    defp filter_skills(skills, nil), do: skills
    defp filter_skills(skills, ""), do: skills

    defp filter_skills(skills, query) do
      query_lower = String.downcase(query)

      Enum.filter(skills, fn skill ->
        String.contains?(String.downcase(skill.name), query_lower) or
          String.contains?(String.downcase(skill.description), query_lower) or
          Enum.any?(skill.tags, &String.contains?(String.downcase(&1), query_lower))
      end)
    end
  end

  defmodule ActivateSkill do
    @moduledoc "Activate a skill by loading its full SKILL.md instructions."

    use CodePuppyControl.Tool

    @impl true
    def name, do: :activate_skill

    @impl true
    def description do
      "Activate a skill by loading its full SKILL.md instructions. " <>
        "Returns the skill content and available resource files."
    end

    @impl true
    def parameters do
      %{
        "type" => "object",
        "properties" => %{
          "skill_name" => %{
            "type" => "string",
            "description" => "Name of the skill to activate"
          }
        },
        "required" => ["skill_name"]
      }
    end

    @impl true
    def invoke(args, _context) do
      skill_name = Map.get(args, "skill_name", "")

      case find_skill(skill_name) do
        {:ok, skill_path, content, resources} ->
          {:ok,
           %{
             skill_name: skill_name,
             content: content,
             resources: resources,
             skill_path: skill_path
           }}

        {:error, reason} ->
          {:error, reason}
      end
    end

    defp find_skill(skill_name) do
      skill_dirs = get_skill_dirs()

      Enum.reduce_while(skill_dirs, {:error, "Skill '#{skill_name}' not found"}, fn dir, acc ->
        skill_dir = Path.join(dir, skill_name)
        skill_md = Path.join(skill_dir, "SKILL.md")

        if File.dir?(skill_dir) and File.exists?(skill_md) do
          case File.read(skill_md) do
            {:ok, content} ->
              resources = get_resources(skill_dir)
              {:halt, {:ok, skill_dir, content, resources}}

            {:error, reason} ->
              {:halt, {:error, "Failed to read SKILL.md: #{:file.format_error(reason)}"}}
          end
        else
          {:cont, acc}
        end
      end)
    end

    defp get_resources(skill_dir) do
      case File.ls(skill_dir) do
        {:ok, entries} ->
          entries
          |> Enum.map(&Path.join(skill_dir, &1))
          |> Enum.filter(&File.regular?/1)
          |> Enum.map(&to_string/1)

        {:error, _} ->
          []
      end
    end

    defp get_skill_dirs do
      home_dir = System.user_home!()
      project_dir = File.cwd!()

      [Path.join(home_dir, ".code_puppy/skills"), Path.join(project_dir, "skills")]
      |> Enum.filter(&File.dir?/1)
    end
  end

  @doc """
  Registers both skill tools with the Tool Registry.
  """
  @spec register_all() :: {:ok, non_neg_integer()}
  def register_all do
    modules = [ListSkills, ActivateSkill]

    Enum.reduce(modules, {:ok, 0}, fn module, {:ok, acc} ->
      case Registry.register(module) do
        :ok -> {:ok, acc + 1}
        {:error, _} -> {:ok, acc}
      end
    end)
  end
end
