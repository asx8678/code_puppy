defmodule Mana.Models.Providers.Anthropic do
  @moduledoc """
  Anthropic Claude API provider implementation.

  Uses Anthropix library if available, otherwise falls back to raw Req.
  Supports both standard completions and SSE streaming.
  """

  @behaviour Mana.Models.Provider

  alias Mana.Config

  @default_base_url "https://api.anthropic.com"
  @api_version "2023-06-01"
  @messages_endpoint "/v1/messages"
  @default_max_tokens 4096

  @impl true
  def provider_id, do: "anthropic"

  @impl true
  def validate_config(config) do
    api_key = config[:api_key] || Config.api_key("anthropic")

    if is_binary(api_key) and api_key != "" do
      :ok
    else
      {:error, "Missing Anthropic API key"}
    end
  end

  @impl true
  def complete(messages, model, opts \\ []) do
    api_key = get_api_key(opts)

    case validate_config(%{api_key: api_key}) do
      :ok ->
        do_complete(messages, model, api_key, opts)

      error ->
        error
    end
  end

  defp do_complete(messages, model, api_key, opts) do
    url = @default_base_url <> @messages_endpoint

    body = %{
      "model" => model,
      "messages" => convert_messages(messages),
      "max_tokens" => Keyword.get(opts, :max_tokens, @default_max_tokens)
    }

    body = maybe_add_temperature(body, opts)

    body = maybe_add_system_from_messages(body, messages, opts)
    body = maybe_add_system_prompt(body, opts)
    body = maybe_add_tools(body, opts)

    headers = [
      {"x-api-key", api_key},
      {"anthropic-version", @api_version},
      {"Content-Type", "application/json"}
    ]

    case Req.post(url, headers: headers, json: body, receive_timeout: 60_000) do
      {:ok, %{status: 200, body: response_body}} ->
        parse_completion_response(response_body, model)

      {:ok, %{status: 429} = resp} ->
        Mana.RateLimiter.report_rate_limit(model)
        retry_after = parse_retry_after(resp)
        {:error, "Rate limited (429), retry after #{retry_after}s: #{format_error(resp.body)}"}

      {:ok, %{status: status, body: error_body}} ->
        {:error, "HTTP #{status}: #{format_error(error_body)}"}

      {:error, reason} ->
        {:error, "Request failed: #{inspect(reason)}"}
    end
  end

  @impl true
  def stream(messages, model, opts \\ []) do
    api_key = get_api_key(opts)

    case validate_config(%{api_key: api_key}) do
      :ok ->
        do_stream(messages, model, api_key, opts)

      error ->
        Stream.resource(
          fn -> error end,
          fn
            nil -> {:halt, nil}
            {:error, _reason} = err -> {[err], nil}
            err -> {[{:error, err}], nil}
          end,
          fn _ -> :ok end
        )
    end
  end

  defp do_stream(messages, model, api_key, opts) do
    url = @default_base_url <> @messages_endpoint

    body = %{
      "model" => model,
      "messages" => convert_messages(messages),
      "max_tokens" => Keyword.get(opts, :max_tokens, @default_max_tokens),
      "stream" => true
    }

    body = maybe_add_temperature(body, opts)
    body = maybe_add_system_from_messages(body, messages, opts)
    body = maybe_add_system_prompt(body, opts)
    body = maybe_add_tools(body, opts)

    headers = [
      {"x-api-key", api_key},
      {"anthropic-version", @api_version},
      {"Content-Type", "application/json"},
      {"Accept", "text/event-stream"}
    ]

    Stream.resource(
      fn ->
        request =
          Req.new(
            method: :post,
            url: url,
            headers: headers,
            json: body,
            into: :self,
            receive_timeout: 600_000
          )

        case Req.request(request) do
          {:ok, %{status: 200} = resp} ->
            {:streaming, resp, ""}

          {:ok, %{status: 429} = resp} ->
            Mana.RateLimiter.report_rate_limit(model)
            retry_after = parse_retry_after(resp)
            {:error, "Rate limited (429), retry after #{retry_after}s"}

          {:ok, %{status: status, body: error_body}} ->
            {:error, "HTTP #{status}: #{format_error(error_body)}"}

          {:error, reason} ->
            {:error, "Request failed: #{inspect(reason)}"}
        end
      end,
      fn
        {:error, msg} ->
          {[{:error, msg}], :halt}

        :halt ->
          {:halt, :halt}

        {:streaming, resp, buffer} ->
          receive do
            message ->
              case Req.parse_message(resp, message) do
                {:ok, [data: chunk]} ->
                  {events, new_buffer} = parse_sse_chunk(buffer <> chunk)
                  stream_events = Enum.flat_map(events, &parse_anthropic_event/1)
                  {stream_events, {:streaming, resp, new_buffer}}

                {:ok, [:done]} ->
                  {[{:part_end, :done}], :halt}

                :unknown ->
                  {[], {:streaming, resp, buffer}}
              end
          after
            60_000 -> {[{:error, :timeout}], :halt}
          end
      end,
      fn
        {:streaming, resp, _} -> Req.cancel_async_response(resp)
        _ -> :ok
      end
    )
  end

  # SSE Processing for Anthropic

  defp parse_sse_chunk(data) do
    lines = String.split(data, "\n")

    # Last element may be an incomplete line — keep it as the new buffer
    {complete_lines, [remainder]} = Enum.split(lines, -1)

    events =
      complete_lines
      |> Enum.filter(&String.starts_with?(&1, "data: "))
      |> Enum.map(fn line ->
        case String.trim_leading(line, "data: ") do
          "[DONE]" -> :done
          json -> decode_sse_json(json)
        end
      end)

    {events, remainder}
  end

  defp decode_sse_json(json) do
    case Jason.decode(json) do
      {:ok, decoded} -> decoded
      {:error, _} -> {:error, "Invalid JSON: #{json}"}
    end
  end

  defp parse_anthropic_event(:done), do: [{:part_end, :done}]
  defp parse_anthropic_event({:error, _} = err), do: [err]

  defp parse_anthropic_event(event) when is_map(event) do
    case event["type"] do
      "message_start" -> [{:part_start, :message}]
      "content_block_start" -> parse_content_block_start(event)
      "content_block_delta" -> parse_content_block_delta(event)
      "content_block_stop" -> [{:part_end, :content}]
      "message_delta" -> [{:part_end, :message}]
      "message_stop" -> [{:part_end, :done}]
      "error" -> parse_error_event(event)
      _ -> []
    end
  end

  defp parse_content_block_start(event) do
    content_block = event["content_block"] || %{}
    index = event["index"] || 0

    case content_block["type"] do
      "text" -> [{:part_start, :content}]
      "tool_use" -> [{:part_start, {:tool_call, index}}]
      _ -> []
    end
  end

  defp parse_content_block_delta(event) do
    delta = event["delta"] || %{}
    index = event["index"] || 0

    cond do
      delta["text"] -> [{:part_delta, :content, delta["text"]}]
      delta["partial_json"] -> [{:part_delta, {:tool_call, index}, delta["partial_json"]}]
      true -> []
    end
  end

  defp parse_error_event(event) do
    error = event["error"] || %{}
    [{:error, error["message"] || "Unknown error"}]
  end

  # Message conversion

  defp convert_messages(messages) when is_list(messages) do
    # Filter out system messages — they should be passed via the "system" parameter
    messages
    |> Enum.reject(fn msg ->
      role = msg["role"] || msg[:role]
      role == "system" or role == :system
    end)
    |> Enum.map(fn msg ->
      case msg do
        %{"role" => role, "content" => content} ->
          %{"role" => convert_role(role), "content" => content}

        %{role: role, content: content} ->
          %{"role" => convert_role(role), "content" => content}

        _ ->
          msg
      end
    end)
  end

  defp convert_messages(messages), do: messages

  defp convert_role("system"), do: "user"
  defp convert_role(role), do: role

  # Response parsing

  defp parse_completion_response(body, model) when is_map(body) do
    content_blocks = body["content"] || []

    content =
      content_blocks
      |> Enum.filter(fn block -> block["type"] == "text" end)
      |> Enum.map_join("", fn block -> block["text"] || "" end)

    # Extract tool_use blocks as tool_calls in OpenAI-compatible format
    tool_calls =
      content_blocks
      |> Enum.filter(fn block -> block["type"] == "tool_use" end)
      |> Enum.with_index()
      |> Enum.map(fn {block, index} ->
        %{
          "id" => block["id"],
          "type" => "function",
          "index" => index,
          "function" => %{
            "name" => block["name"],
            "arguments" => Jason.encode!(block["input"] || %{})
          }
        }
      end)

    usage = body["usage"] || %{}

    {:ok,
     %{
       content: content,
       tool_calls: Mana.Message.normalize_keys(tool_calls),
       usage: usage,
       model: model
     }}
  end

  defp parse_completion_response(_body, _model) do
    {:error, "Invalid response format"}
  end

  # Helper functions

  defp get_api_key(opts) do
    Keyword.get(opts, :api_key) || Config.api_key("anthropic")
  end

  defp maybe_add_temperature(body, opts) do
    case Keyword.get(opts, :temperature) do
      nil -> body
      temp -> Map.put(body, "temperature", temp)
    end
  end

  defp maybe_add_system_prompt(body, opts) do
    case Keyword.get(opts, :system) do
      nil -> body
      system -> Map.put(body, "system", system)
    end
  end

  defp maybe_add_tools(body, opts) do
    case Keyword.get(opts, :tools) do
      nil -> body
      tools -> Map.put(body, "tools", tools)
    end
  end

  defp maybe_add_system_from_messages(body, messages, opts) do
    system_text =
      messages
      |> Enum.filter(fn msg ->
        role = msg["role"] || msg[:role]
        role == "system" or role == :system
      end)
      |> Enum.map_join("\n\n", fn msg -> msg["content"] || msg[:content] end)

    if system_text != "" and not Keyword.has_key?(opts, :system) do
      Map.put(body, "system", system_text)
    else
      body
    end
  end

  defp parse_retry_after(%{headers: headers}) do
    case headers["retry-after"] do
      [value | _] ->
        case Integer.parse(value) do
          {seconds, _} -> seconds
          :error -> 60
        end

      _ ->
        60
    end
  end

  defp format_error(%{__struct__: _} = body), do: inspect(body)

  defp format_error(body) when is_map(body) do
    error = body["error"] || %{}
    error["message"] || inspect(body)
  end

  defp format_error(body), do: inspect(body)
end
