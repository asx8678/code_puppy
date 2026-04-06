defmodule Mana.Agent.ToolPruning do
  @moduledoc "Pure functions for tool call pruning"

  @doc "Remove tool calls that don't have matching returns"
  @spec prune_interrupted([map()]) :: [map()]
  def prune_interrupted(messages) do
    tool_call_ids = collect_tool_call_ids(messages)
    tool_return_ids = collect_tool_return_ids(messages)

    # Tool calls that never got a return
    interrupted_calls = MapSet.difference(tool_call_ids, tool_return_ids)
    # Tool returns without a matching call (orphaned)
    orphaned_returns = MapSet.difference(tool_return_ids, tool_call_ids)

    # Remove both orphaned returns and messages with interrupted tool calls
    Enum.reject(messages, fn msg ->
      # Remove orphaned tool returns
      # Remove assistant messages with interrupted tool calls
      orphaned_return?(msg, orphaned_returns) or
        has_interrupted_tool_call?(msg, interrupted_calls)
    end)
  end

  defp orphaned_return?(%{tool_call_id: id}, orphaned_returns) do
    MapSet.member?(orphaned_returns, id)
  end

  defp orphaned_return?(_, _), do: false

  defp has_interrupted_tool_call?(%{tool_calls: calls}, interrupted_calls) do
    Enum.any?(calls, fn call ->
      id = Map.get(call, :id)
      id != nil and MapSet.member?(interrupted_calls, id)
    end)
  end

  defp has_interrupted_tool_call?(_, _), do: false

  @doc "Find a safe split index for history truncation"
  @spec find_safe_split_index([map()], non_neg_integer()) :: non_neg_integer()
  def find_safe_split_index(messages, target_tokens) do
    {index, _} =
      Enum.reduce(messages, {0, 0}, fn _msg, {idx, tokens} ->
        if tokens >= target_tokens do
          {idx, tokens}
        else
          {idx + 1, tokens + 50}
        end
      end)

    max(0, index - 1)
  end

  @doc "Collect all tool_call_ids from assistant messages"
  @spec collect_tool_call_ids([map()]) :: MapSet.t()
  def collect_tool_call_ids(messages) do
    messages
    |> Enum.filter(&Map.has_key?(&1, :tool_calls))
    |> Enum.flat_map(& &1.tool_calls)
    |> Enum.map(&Map.get(&1, :id))
    |> Enum.reject(&is_nil/1)
    |> MapSet.new()
  end

  defp collect_tool_return_ids(messages) do
    messages
    |> Enum.filter(&Map.has_key?(&1, :tool_call_id))
    |> Enum.map(& &1.tool_call_id)
    |> Enum.reject(&is_nil/1)
    |> MapSet.new()
  end
end
