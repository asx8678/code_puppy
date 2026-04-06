defmodule Mana.Agent.History do
  @moduledoc "Pure functions for message history management"

  @doc "Hash a message for deduplication"
  @spec hash_message(map()) :: integer()
  def hash_message(message) do
    :erlang.phash2(message)
  end

  @doc "Deduplicate messages using MapSet"
  @spec deduplicate([map()], MapSet.t()) :: {[map()], MapSet.t()}
  def deduplicate(messages, seen_hashes \\ MapSet.new()) do
    {unique, new_seen} =
      Enum.reduce(messages, {[], seen_hashes}, fn msg, {acc, seen} ->
        hash = hash_message(msg)

        if MapSet.member?(seen, hash) do
          {acc, seen}
        else
          {[msg | acc], MapSet.put(seen, hash)}
        end
      end)

    {Enum.reverse(unique), new_seen}
  end

  @doc "Ensure the last message is a user request"
  @spec ensure_ends_with_request([map()]) :: [map()]
  def ensure_ends_with_request([]), do: []

  def ensure_ends_with_request(messages) do
    case List.last(messages) do
      %{role: "user"} -> messages
      _ -> messages ++ [%{role: "user", content: "Continue"}]
    end
  end

  @doc "Remove binary/large content from messages"
  @spec clean_binaries([map()]) :: [map()]
  def clean_binaries(messages) do
    Enum.map(messages, fn msg ->
      case Map.get(msg, :content) do
        content when is_binary(content) and byte_size(content) > 10_000 ->
          Map.put(msg, :content, "[content truncated: #{byte_size(content)} bytes]")

        _ ->
          msg
      end
    end)
  end

  @doc "Accumulate new messages into history (the pydantic-ai pattern)"
  @spec accumulate([map()], [map()], keyword()) :: [map()]
  def accumulate(history, new_messages, opts \\ []) do
    max_history = Keyword.get(opts, :max_history, 100)
    combined = history ++ new_messages
    {deduped, _seen} = deduplicate(combined)

    if length(deduped) > max_history do
      Enum.take(deduped, -max_history)
    else
      deduped
    end
  end
end
