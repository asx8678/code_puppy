defmodule Mana.Models.Providers.SSE do
  @moduledoc """
  Shared Server-Sent Events parsing for LLM provider streaming.

  Used by Anthropic and OpenAI providers to parse SSE data chunks,
  decode JSON payloads, handle retry headers, and format errors.
  """

  @doc """
  Parses an SSE data chunk into events and a remainder buffer.

  Returns `{events, remainder}` where events is a list of:
  - decoded maps (from JSON)
  - `:done` atom (terminal marker)
  - `{:error, reason}` tuples (malformed JSON)

  ## Examples

      iex> Mana.Models.Providers.SSE.parse_chunk("data: {\"hello\":1}\\n\\ndata: [DONE]\\n\\ndata: ")
      {[%{"hello" => 1}, :done], "data: "}
  """
  @spec parse_chunk(String.t()) :: {[term()], String.t()}
  def parse_chunk(data) do
    lines = String.split(data, ~r/\r?\n/)

    # Last element may be an incomplete line — keep it as the new buffer
    {complete_lines, [remainder]} = Enum.split(lines, -1)

    events =
      complete_lines
      |> Enum.filter(&String.starts_with?(&1, "data: "))
      |> Enum.map(fn line ->
        case String.trim_leading(line, "data: ") do
          "[DONE]" -> :done
          json -> decode_json(json)
        end
      end)

    {events, remainder}
  end

  @doc "Decodes a JSON string, returning the decoded map or an error tuple."
  @spec decode_json(String.t()) :: map() | {:error, String.t()}
  def decode_json(json) do
    case Jason.decode(json) do
      {:ok, decoded} -> decoded
      {:error, _} -> {:error, "Invalid JSON: #{json}"}
    end
  end

  @doc "Extracts a Retry-After header value in seconds (default 60)."
  @spec parse_retry_after(map()) :: non_neg_integer()
  def parse_retry_after(%{headers: headers}) when is_map(headers) do
    case headers["retry-after"] do
      [value | _] ->
        case Integer.parse(value) do
          {seconds, _} when seconds > 0 -> seconds
          _ -> 60
        end

      _ ->
        60
    end
  end

  def parse_retry_after(_), do: 60

  @doc "Formats an API error body into a human-readable string."
  @spec format_error(term()) :: String.t()
  def format_error(%{__struct__: _} = body), do: inspect(body)

  def format_error(body) when is_map(body) do
    error = body["error"] || %{}
    error["message"] || inspect(body)
  end

  def format_error(body), do: inspect(body)
end
