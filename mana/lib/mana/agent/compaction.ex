defmodule Mana.Agent.Compaction do
  @moduledoc "Pure functions for history compaction"
  alias Mana.Agent.TokenEstimation

  @doc "Check if compaction is needed"
  @spec should_compact?([map()], non_neg_integer()) :: boolean()
  def should_compact?(messages, token_limit \\ 8000) do
    total_tokens =
      Enum.reduce(messages, 0, fn msg, acc ->
        acc + TokenEstimation.estimate_message(msg)
      end)

    total_tokens > token_limit
  end

  @doc "Split history for summarization"
  @spec split_for_summarization([map()], non_neg_integer()) :: {[map()], [map()]}
  def split_for_summarization(messages, keep_recent \\ 10) do
    if length(messages) <= keep_recent do
      {[], messages}
    else
      {to_summarize, recent} = Enum.split(messages, length(messages) - keep_recent)
      {to_summarize, recent}
    end
  end

  @doc "Compact history by removing/filtering large messages"
  @spec compact([map()], keyword()) :: [map()]
  def compact(messages, opts \\ []) do
    max_tokens = Keyword.get(opts, :max_tokens, 8000)

    messages
    |> filter_huge_messages()
    |> trim_to_token_limit(max_tokens)
  end

  @doc "Filter out excessively large messages"
  @spec filter_huge_messages([map()]) :: [map()]
  def filter_huge_messages(messages, max_size \\ 50_000) do
    Enum.map(messages, fn msg ->
      case Map.get(msg, :content) do
        content when is_binary(content) and byte_size(content) >= max_size ->
          Map.put(msg, :content, "[message too large: #{byte_size(content)} bytes]")

        _ ->
          msg
      end
    end)
  end

  defp trim_to_token_limit(messages, max_tokens) do
    {trimmed, _} =
      Enum.reduce(Enum.reverse(messages), {[], 0}, fn msg, {acc, tokens} ->
        msg_tokens = TokenEstimation.estimate_message(msg)

        if tokens + msg_tokens <= max_tokens do
          {[msg | acc], tokens + msg_tokens}
        else
          {acc, tokens}
        end
      end)

    trimmed
  end
end
