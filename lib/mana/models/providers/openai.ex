defmodule Mana.Models.Providers.OpenAI do
  @moduledoc """
  OpenAI API provider implementation using Req.

  Supports both standard completions and SSE streaming.
  """

  @behaviour Mana.Models.Provider

  alias Mana.Config
  alias Mana.Models.Providers.SSE
  alias Mana.Streaming.SSEParser

  @model_telemetry_prefix [:mana, :model, :request]
  @default_base_url "https://api.openai.com/v1"
  @chat_completions_endpoint "/chat/completions"

  @impl true
  def provider_id, do: "openai"

  @impl true
  def validate_config(config) do
    api_key = config[:api_key] || Config.api_key("openai")

    if is_binary(api_key) and api_key != "" do
      :ok
    else
      {:error, "Missing OpenAI API key"}
    end
  end

  @impl true
  def complete(messages, model, opts \\ []) do
    api_key = get_api_key(opts)
    base_url = Keyword.get(opts, :base_url, @default_base_url)

    case validate_config(%{api_key: api_key}) do
      :ok ->
        start_meta = %{
          provider: provider_id(),
          model_name: model,
          estimated_tokens: estimate_tokens(messages)
        }

        :telemetry.span(
          @model_telemetry_prefix,
          start_meta,
          fn ->
            result = do_complete(messages, model, api_key, base_url, opts)

            case result do
              {:ok, %{usage: usage}} = ok ->
                tokens_in = usage["prompt_tokens"] || 0
                tokens_out = usage["completion_tokens"] || 0

                {ok,
                 %{
                   provider: provider_id(),
                   model_name: model,
                   tokens_in: tokens_in,
                   tokens_out: tokens_out
                 }}

              {:error, reason} = err ->
                {err,
                 %{
                   provider: provider_id(),
                   model_name: model,
                   error_type: classify_error(reason)
                 }}
            end
          end
        )

      error ->
        error
    end
  end

  defp do_complete(messages, model, api_key, base_url, opts) do
    url = base_url <> @chat_completions_endpoint

    body = %{
      "model" => model,
      "messages" => messages,
      "stream" => false
    }

    body = maybe_add_temperature(body, opts)
    body = maybe_add_max_tokens(body, opts)
    body = maybe_add_tools(body, opts)

    headers = [
      {"Authorization", "Bearer #{api_key}"},
      {"Content-Type", "application/json"}
    ]

    case Req.post(url, headers: headers, json: body, receive_timeout: 60_000) do
      {:ok, %{status: 200, body: response_body}} ->
        parse_completion_response(response_body, model)

      {:ok, %{status: 429} = resp} ->
        Mana.RateLimiter.report_rate_limit(model)
        retry_after = SSE.parse_retry_after(resp)
        {:error, "Rate limited (429), retry after #{retry_after}s: #{SSE.format_error(resp.body)}"}

      {:ok, %{status: status, body: error_body}} ->
        {:error, "HTTP #{status}: #{SSE.format_error(error_body)}"}

      {:error, reason} ->
        {:error, "Request failed: #{inspect(reason)}"}
    end
  end

  @impl true
  def stream(messages, model, opts \\ []) do
    api_key = get_api_key(opts)
    base_url = Keyword.get(opts, :base_url, @default_base_url)

    case validate_config(%{api_key: api_key}) do
      :ok ->
        do_stream(messages, model, api_key, base_url, opts)

      error ->
        # Return a stream that yields just the error
        SSEParser.error_stream(error)
    end
  end

  defp do_stream(messages, model, api_key, base_url, opts) do
    url = base_url <> @chat_completions_endpoint

    body = %{
      "model" => model,
      "messages" => messages,
      "stream" => true
    }

    body = maybe_add_temperature(body, opts)
    body = maybe_add_max_tokens(body, opts)
    body = maybe_add_tools(body, opts)

    headers = [
      {"Authorization", "Bearer #{api_key}"},
      {"Content-Type", "application/json"},
      {"Accept", "text/event-stream"}
    ]

    request =
      SSEParser.build_request(
        url: url,
        headers: headers,
        body: body
      )

    SSEParser.stream(
      fn ->
        SSEParser.init_stream_request(
          request,
          model,
          error_msg: "Rate limited",
          format_fn: &SSE.format_error/1
        )
      end,
      &parse_sse_event/1,
      timeout: 60_000
    )
  end

  # SSE event parsing

  defp parse_sse_event(:done), do: [{:part_end, :done}]
  defp parse_sse_event({:error, _} = err), do: [err]

  defp parse_sse_event(event) when is_map(event) do
    event
    |> Map.get("choices", [])
    |> Enum.flat_map(&parse_choice/1)
  end

  defp parse_choice(choice) do
    delta = choice["delta"] || %{}
    finish_reason = choice["finish_reason"]

    events = []
    events = maybe_add_content_delta(events, delta)
    events = maybe_add_tool_calls(events, delta["tool_calls"])
    events = maybe_add_finish_event(events, finish_reason)

    events
  end

  defp maybe_add_content_delta(events, delta) do
    case delta["content"] do
      nil -> events
      content -> [{:part_delta, :content, content} | events]
    end
  end

  defp maybe_add_tool_calls(events, nil), do: events
  defp maybe_add_tool_calls(events, []), do: events

  defp maybe_add_tool_calls(events, tool_calls) do
    Enum.reduce(tool_calls, events, &parse_tool_call/2)
  end

  defp parse_tool_call(tool_call, acc) do
    case tool_call["function"] do
      nil ->
        acc

      func ->
        acc
        |> maybe_add_tool_start(func, tool_call)
        |> maybe_add_tool_delta(func, tool_call)
    end
  end

  defp maybe_add_tool_start(acc, func, tool_call) do
    if func["name"] do
      acc ++ [{:part_start, {:tool_call, tool_call["index"] || 0}}]
    else
      acc
    end
  end

  defp maybe_add_tool_delta(acc, func, tool_call) do
    if func["arguments"] do
      acc ++ [{:part_delta, {:tool_call, tool_call["index"] || 0}, func["arguments"]}]
    else
      acc
    end
  end

  defp maybe_add_finish_event(events, "stop"), do: events ++ [{:part_end, :content}]
  defp maybe_add_finish_event(events, "tool_calls"), do: events ++ [{:part_end, :tool_calls}]
  defp maybe_add_finish_event(events, _), do: events

  # Response parsing

  defp parse_completion_response(body, model) when is_map(body) do
    choices = body["choices"] || []

    case List.first(choices) do
      nil ->
        {:error, "No choices in response"}

      choice ->
        message = choice["message"] || %{}
        content = message["content"] || ""
        tool_calls = message["tool_calls"] || []
        usage = body["usage"] || %{}

        {:ok,
         %{
           content: content,
           tool_calls: Mana.Message.normalize_keys(tool_calls),
           usage: usage,
           model: model
         }}
    end
  end

  defp parse_completion_response(_body, _model) do
    {:error, "Invalid response format"}
  end

  # Helper functions

  defp get_api_key(opts) do
    Keyword.get(opts, :api_key) || Config.api_key("openai")
  end

  defp maybe_add_temperature(body, opts) do
    case Keyword.get(opts, :temperature) do
      nil -> body
      temp -> Map.put(body, "temperature", temp)
    end
  end

  defp maybe_add_max_tokens(body, opts) do
    case Keyword.get(opts, :max_tokens) do
      nil -> body
      tokens -> Map.put(body, "max_tokens", tokens)
    end
  end

  defp maybe_add_tools(body, opts) do
    case Keyword.get(opts, :tools) do
      nil -> body
      tools -> Map.put(body, "tools", tools)
    end
  end

  defp estimate_tokens(messages) when is_list(messages) do
    messages
    |> Enum.map(fn msg ->
      case msg do
        %{"content" => content} when is_binary(content) -> content
        %{content: content} when is_binary(content) -> content
        _ -> ""
      end
    end)
    |> Enum.join()
    |> String.length()
    |> div(4)
  end

  defp estimate_tokens(_), do: 0

  defp classify_error(reason) when is_binary(reason) do
    cond do
      String.contains?(reason, "429") -> :rate_limit
      String.contains?(reason, "401") -> :auth
      String.contains?(reason, "403") -> :auth
      String.contains?(reason, "timeout") -> :timeout
      String.contains?(reason, "Timeout") -> :timeout
      true -> :unknown
    end
  end

  defp classify_error(_), do: :unknown
end
