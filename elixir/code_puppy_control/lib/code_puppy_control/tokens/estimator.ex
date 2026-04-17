defmodule CodePuppyControl.Tokens.Estimator do
  @moduledoc "Token estimation - minimal version for pruning. Full version in bd-44."

  @sampling_threshold 500
  @code_detection_ratio 0.3

  def estimate_tokens(""), do: 1

  def estimate_tokens(text) do
    char_count = String.length(text)
    ratio = if is_code_heavy(text), do: 4.5, else: 4.0

    if char_count <= @sampling_threshold do
      max(1, floor(char_count / ratio))
    else
      # Sampling path - sample ~1% of lines
      lines = String.split(text, "\n")
      num_lines = length(lines)
      step = max(div(num_lines, 100), 1)

      sample_len =
        lines
        |> Enum.with_index()
        |> Enum.filter(fn {_, i} -> rem(i, step) == 0 end)
        |> Enum.map(fn {line, _} -> String.length(line) + 1 end)
        |> Enum.sum()

      if sample_len == 0,
        do: max(1, floor(char_count / ratio)),
        else: max(1, floor(sample_len / ratio / sample_len * char_count))
    end
  end

  def stringify_part_for_tokens(part) do
    # Build string from part for token estimation
    base = (part["part_kind"] || "") <> ": "
    content = part["content"]
    json = part["content_json"]

    cond do
      content && content != "" -> content
      json -> json
      true -> base
    end
    |> then(fn text ->
      tool = part["tool_name"]

      if tool && tool != "" do
        args = part["args"] || ""
        text <> tool <> " " <> args
      else
        text
      end
    end)
  end

  defp is_code_heavy(text) when byte_size(text) < 20, do: false

  defp is_code_heavy(text) do
    sample = String.slice(text, 0, 2000)
    lines = String.split(sample, "\n")
    line_count = max(length(lines), 1)
    code_lines = Enum.count(lines, &line_has_code_indicators/1)
    code_lines / line_count > @code_detection_ratio
  end

  defp line_has_code_indicators(line) do
    String.contains?(line, ["{", "}", "[", "]", "(", ")", ";"]) or
      keyword_start?(String.trim_leading(line))
  end

  defp keyword_start?(l) do
    Enum.any?(
      [
        "def ",
        "class ",
        "import ",
        "from ",
        "if ",
        "for ",
        "while ",
        "return ",
        "function ",
        "const ",
        "let ",
        "var ",
        "=>",
        "#include"
      ],
      &String.starts_with?(l, &1)
    )
  end
end
