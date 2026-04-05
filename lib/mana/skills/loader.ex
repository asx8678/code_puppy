defmodule Mana.Skills.Loader do
  @moduledoc "Loads skills from SKILL.md files"

  @user_skills_dir Path.expand("~/.mana/skills")
  @project_skills_dir "./skills"

  @doc "Discover and load all skills"
  @spec load() :: [map()]
  def load do
    user_skills = load_from_dir(@user_skills_dir)
    project_skills = load_from_dir(@project_skills_dir)
    user_skills ++ project_skills
  end

  @doc "Load skills from a directory"
  def load_from_dir(dir) do
    case File.ls(dir) do
      {:ok, files} ->
        files
        |> Enum.filter(&String.ends_with?(&1, ".md"))
        |> Enum.map(fn file ->
          path = Path.join(dir, file)
          parse_file(path)
        end)
        |> Enum.reject(&is_nil/1)

      {:error, _} ->
        []
    end
  end

  defp parse_file(path) do
    case File.read(path) do
      {:ok, content} ->
        case String.split(content, "---", parts: 3) do
          ["", frontmatter, body] ->
            parse_frontmatter(frontmatter, String.trim(body), path)

          _ ->
            nil
        end

      {:error, _} ->
        nil
    end
  end

  defp parse_frontmatter(frontmatter, body, path) do
    fields =
      frontmatter
      |> String.split("\n")
      |> Enum.map(fn line ->
        case String.split(line, ":", parts: 2) do
          [key, value] -> {String.trim(key), String.trim(value)}
          _ -> nil
        end
      end)
      |> Enum.reject(&is_nil/1)
      |> Map.new()

    name = Map.get(fields, "name", path |> Path.basename() |> Path.rootname())

    %{
      name: name,
      description: Map.get(fields, "description", ""),
      version: Map.get(fields, "version", "1.0.0"),
      author: Map.get(fields, "author", "unknown"),
      tags: parse_tags(Map.get(fields, "tags", "")),
      content: body,
      source: path
    }
  end

  defp parse_tags(""), do: []

  defp parse_tags(tags) do
    tags
    |> String.split(",")
    |> Enum.map(&String.trim/1)
    |> Enum.reject(&(&1 == ""))
  end
end
