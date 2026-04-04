defmodule Mana.Agent.TokenEstimation do
  @moduledoc "Pure token estimation functions"

  @doc "Estimate token count from string (rough: byte_size / 3)"
  @spec estimate_count(String.t()) :: non_neg_integer()
  def estimate_count(text) when is_binary(text) do
    div(byte_size(text), 3)
  end

  @doc "Estimate tokens for a message (content + overhead)"
  @spec estimate_message(map()) :: non_neg_integer()
  def estimate_message(%{content: content}) when is_binary(content) do
    estimate_count(content) + 4
  end

  def estimate_message(_), do: 4

  @doc "Estimate context overhead (system prompt, tools, etc)"
  @spec estimate_context_overhead(String.t(), [map()]) :: non_neg_integer()
  def estimate_context_overhead(system_prompt, tools \\ []) do
    system_tokens = estimate_count(system_prompt || "")

    tool_tokens =
      Enum.reduce(tools, 0, fn tool, acc ->
        acc +
          estimate_count(Map.get(tool, :name, "")) +
          estimate_count(Map.get(tool, :description, ""))
      end)

    system_tokens + tool_tokens + 100
  end
end
