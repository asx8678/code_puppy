defmodule Mana.Summarization do
  @moduledoc """
  Context compaction via LLM summarization.

  Provides functions for summarizing conversation history and checking
  when messages need to be compacted. Uses the `Mana.Models.Registry`
  to dispatch summarization requests to the appropriate LLM provider.

  ## Usage

      # Check if messages need compaction
      if Mana.Summarization.needs_compaction?(messages, 8000) do
        # Summarize older messages
        {:ok, summary} = Mana.Summarization.summarize(messages_to_summarize)

        # Or use the compact helper
        compacted = Mana.Summarization.compact_with_summary(messages)
      end

  """

  require Logger

  alias Mana.Agent.TokenEstimation
  alias Mana.Models.Registry

  @doc """
  Summarize a conversation history.

  Sends the messages to an LLM for summarization, preserving key information
  while reducing token count.

  ## Parameters

    - `messages` - List of message maps to summarize
    - `opts` - Keyword list of options:
      - `:model` - Model name to use (default: `"claude-sonnet-4-5"`)

  ## Returns

    - `{:ok, String.t()}` - Summarization succeeded
    - `{:error, term()}` - Summarization failed

  """
  @spec summarize([map()], keyword()) :: {:ok, String.t()} | {:error, term()}
  def summarize(messages, opts \\ []) when is_list(messages) do
    model = Keyword.get(opts, :model, "claude-sonnet-4-5")

    prompt = build_summarization_prompt(messages)
    request_messages = [%{role: "user", content: prompt}]

    case Registry.complete(request_messages, model, []) do
      {:ok, %{content: summary}} ->
        Logger.debug("Generated summary: #{String.slice(summary, 0, 100)}...")
        {:ok, summary}

      {:error, reason} = error ->
        Logger.warning("Failed to generate summary: #{inspect(reason)}")
        error
    end
  end

  @doc """
  Check if messages need compaction based on token count.

  ## Parameters

    - `messages` - List of message maps
    - `token_threshold` - Token limit to check against (default: 8000)

  ## Returns

    `true` if the estimated token count exceeds the threshold.

  """
  @spec needs_compaction?([map()], non_neg_integer()) :: boolean()
  def needs_compaction?(messages, token_threshold \\ 8000) when is_list(messages) do
    total =
      Enum.reduce(messages, 0, fn msg, acc ->
        acc + TokenEstimation.estimate_message(msg)
      end)

    total > token_threshold
  end

  @doc """
  Binary-split recursive summarization.

  Splits messages into two parts: older messages to summarize and
  recent messages to keep. Generates a summary of the older messages
  and returns a new message list with the summary prepended to the
  kept messages.

  ## Parameters

    - `messages` - List of message maps to compact
    - `opts` - Keyword list of options:
      - `:keep_recent` - Number of recent messages to keep (default: 10)
      - `:model` - Model name to use for summarization

  ## Returns

    List of messages with a summary message prepended.

  """
  @spec compact_with_summary([map()], keyword()) :: [map()]
  def compact_with_summary(messages, opts \\ []) when is_list(messages) do
    {to_summarize, keep} = split_for_summarization(messages, opts)

    if to_summarize == [] do
      keep
    else
      case summarize(to_summarize, opts) do
        {:ok, summary} ->
          summary_msg = %{
            role: "system",
            content: "[Summary of earlier conversation]: #{summary}"
          }

          [summary_msg | keep]

        {:error, reason} ->
          Logger.warning("Compacting without summary due to error: #{inspect(reason)}")
          keep
      end
    end
  end

  # Build the summarization prompt from conversation messages
  defp build_summarization_prompt(messages) do
    conversation =
      Enum.map_join(messages, "\n", fn msg ->
        role = msg[:role] || Map.get(msg, "role", "user")
        content = msg[:content] || Map.get(msg, "content", "")
        "#{role}: #{content}"
      end)

    """
    Summarize the following conversation concisely, preserving key information:

    #{conversation}

    Provide a brief summary focusing on:
    - Main topics discussed
    - Key decisions made
    - Action items or next steps
    """
  end

  # Split messages for summarization, keeping recent messages intact
  defp split_for_summarization(messages, opts) do
    keep_recent = Keyword.get(opts, :keep_recent, 10)

    if length(messages) <= keep_recent do
      {[], messages}
    else
      Enum.split(messages, length(messages) - keep_recent)
    end
  end
end
