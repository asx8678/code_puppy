defmodule Mana.TTSR.RuleLoader do
  @moduledoc "Loads TTSR rules from markdown files with YAML frontmatter"

  alias Mana.TTSR.Rule

  @user_rules_dir Path.expand("~/.mana/rules")
  @project_rules_dir "./rules"

  @doc "Discover and load all rules from user and project directories"
  @spec load() :: [Rule.t()]
  def load do
    user_rules = load_from_dir(@user_rules_dir)
    project_rules = load_from_dir(@project_rules_dir)
    user_rules ++ project_rules
  end

  @doc "Load rules from a specific directory"
  @spec load_from_dir(String.t()) :: [Rule.t()]
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

  @doc "Parse a single rule file"
  @spec parse_file(String.t()) :: Rule.t() | nil
  def parse_file(path) do
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

    trigger = fields |> Map.get("trigger") |> strip_quotes()

    if trigger do
      scope = parse_scope(Map.get(fields, "scope", "text"))
      repeat = parse_repeat(Map.get(fields, "repeat", "once"))
      name = Map.get(fields, "name", Path.basename(path, ".md"))

      Rule.new(
        name: name,
        trigger: trigger,
        content: body,
        source: path,
        scope: scope,
        repeat: repeat
      )
    else
      nil
    end
  end

  defp strip_quotes(nil), do: nil
  defp strip_quotes("\"" <> rest), do: String.trim_trailing(rest, "\"")
  defp strip_quotes("'" <> rest), do: String.trim_trailing(rest, "'")
  defp strip_quotes(value), do: value

  defp parse_scope("thinking"), do: :thinking
  defp parse_scope("tool"), do: :tool
  defp parse_scope("all"), do: :all
  defp parse_scope(_), do: :text

  defp parse_repeat("once"), do: :once
  defp parse_repeat("always"), do: {:gap, 0}

  defp parse_repeat(<<"gap:", n::binary>>) do
    case Integer.parse(n) do
      {num, _} -> {:gap, num}
      _ -> :once
    end
  end

  defp parse_repeat(_), do: :once
end
