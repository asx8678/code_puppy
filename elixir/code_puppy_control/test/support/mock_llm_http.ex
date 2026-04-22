defmodule CodePuppyControl.Test.MockLLMHTTP do
  @moduledoc """
  Mock HTTP client for LLM provider tests.

  Routes requests to handler functions based on URL patterns.
  Supports both regular JSON responses and SSE streaming responses.

  ## Usage

      # Register a handler
      MockLLMHTTP.register(fn
        :post, url, opts when url =~ "/chat/completions" ->
          {:ok, %{status: 200, body: fixture_json, headers: []}}
      end)

      # Use in provider
      OpenAI.chat(messages, [], http_client: MockLLMHTTP)

      # Clean up
      MockLLMHTTP.reset()
  """

  use Agent

  def child_spec(opts) do
    %{
      id: __MODULE__,
      start: {__MODULE__, :start_link, [opts]},
      type: :worker,
      restart: :transient
    }
  end

  def start_link(_opts \\ []) do
    Agent.start_link(fn -> [] end, name: __MODULE__)
  end

  def register(handler_fn) do
    ensure_started()
    Agent.update(__MODULE__, fn handlers -> [handler_fn | handlers] end)
  end

  def reset do
    ensure_started()
    Agent.update(__MODULE__, fn _ -> [] end)
  end

  @doc false
  def request(method, url, opts) do
    ensure_started()
    handlers = Agent.get(__MODULE__, & &1)

    Enum.reduce_while(handlers, {:error, :no_handler}, fn handler, _acc ->
      case handler.(method, url, opts) do
        {:passthrough} -> {:cont, {:error, :no_handler}}
        result -> {:halt, result}
      end
    end)
  end

  @doc false
  def stream(method, url, opts) do
    # Mimics HttpClient.stream: lazy Stream yielding {:data, chunk} then {:done, metadata}
    Stream.resource(
      fn -> {request(method, url, Keyword.put(opts, :stream_request, true)), false} end,
      fn
        {{:ok, %{status: status, body: body, headers: headers}}, false} ->
          {[{:data, body}], {{:ok, %{status: status, headers: headers}}, true}}

        {{:ok, %{status: status, headers: headers}}, true} ->
          {[{:done, %{status: status, headers: headers}}], :done}

        {{:error, reason}, _} ->
          {[{:error, reason}], :done}

        :done ->
          {:halt, :done}
      end,
      fn _ -> :ok end
    )
  end

  @doc """
  Starts the mock under a supervisor. Preferred in test setup:

      setup do
        MockLLMHTTP.start_supervised()
        :ok
      end
  """
  @spec start_supervised() :: :ok
  def start_supervised do
    case Process.whereis(__MODULE__) do
      nil ->
        {:ok, _pid} =
          ExUnit.Callbacks.start_supervised(%{
            id: __MODULE__,
            start: {__MODULE__, :start_link, [[]]},
            type: :worker,
            restart: :transient
          })

        :ok

      _pid ->
        :ok
    end
  end

  defp ensure_started do
    case Process.whereis(__MODULE__) do
      nil ->
        raise "MockLLMHTTP not started under supervision. " <>
                "Add MockLLMHTTP.start_supervised() to your test setup, " <>
                "or start it under your own supervisor. " <>
                "Unsupervised starts are forbidden to prevent test leaks."

      _ ->
        :ok
    end
  end

  # ── Fixture Helpers ───────────────────────────────────────────────────────

  def openai_chat_fixture(opts \\ []) do
    id = Keyword.get(opts, :id, "chatcmpl-test123")
    model = Keyword.get(opts, :model, "gpt-4o")
    content = Keyword.get(opts, :content, "Hello! How can I help you?")
    finish_reason = Keyword.get(opts, :finish_reason, "stop")
    tool_calls = Keyword.get(opts, :tool_calls, nil)

    message = %{"role" => "assistant", "content" => content}
    message = if tool_calls, do: Map.put(message, "tool_calls", tool_calls), else: message

    %{
      "id" => id,
      "object" => "chat.completion",
      "model" => model,
      "choices" => [%{"index" => 0, "message" => message, "finish_reason" => finish_reason}],
      "usage" => %{"prompt_tokens" => 10, "completion_tokens" => 20, "total_tokens" => 30}
    }
    |> Jason.encode!()
  end

  def openai_stream_fixture(opts \\ []) do
    chunks = Keyword.get(opts, :chunks, ["Hello", " there", "!"])
    model = Keyword.get(opts, :model, "gpt-4o")
    id = Keyword.get(opts, :id, "chatcmpl-stream123")

    parts =
      Enum.map(chunks, fn text ->
        data = %{
          "id" => id,
          "object" => "chat.completion.chunk",
          "model" => model,
          "choices" => [%{"index" => 0, "delta" => %{"content" => text}, "finish_reason" => nil}]
        }

        "data: #{Jason.encode!(data)}\n\n"
      end)

    final = %{
      "id" => id,
      "object" => "chat.completion.chunk",
      "model" => model,
      "choices" => [%{"index" => 0, "delta" => %{}, "finish_reason" => "stop"}],
      "usage" => %{"prompt_tokens" => 10, "completion_tokens" => 3, "total_tokens" => 13}
    }

    (parts ++ ["data: #{Jason.encode!(final)}\n\n", "data: [DONE]\n\n"])
    |> Enum.join()
  end

  def openai_tool_stream_fixture(opts \\ []) do
    id = Keyword.get(opts, :id, "chatcmpl-tool123")
    model = Keyword.get(opts, :model, "gpt-4o")
    tool_name = Keyword.get(opts, :tool_name, "get_weather")
    tool_call_id = Keyword.get(opts, :tool_call_id, "call_abc123")
    arguments = Keyword.get(opts, :arguments, ~s({"location": "Boston"}))

    chunks = [
      %{
        "id" => id,
        "object" => "chat.completion.chunk",
        "model" => model,
        "choices" => [
          %{
            "index" => 0,
            "delta" => %{
              "tool_calls" => [
                %{
                  "index" => 0,
                  "id" => tool_call_id,
                  "type" => "function",
                  "function" => %{"name" => tool_name, "arguments" => ""}
                }
              ]
            },
            "finish_reason" => nil
          }
        ]
      },
      %{
        "id" => id,
        "object" => "chat.completion.chunk",
        "model" => model,
        "choices" => [
          %{
            "index" => 0,
            "delta" => %{
              "tool_calls" => [%{"index" => 0, "function" => %{"arguments" => arguments}}]
            },
            "finish_reason" => nil
          }
        ]
      },
      %{
        "id" => id,
        "object" => "chat.completion.chunk",
        "model" => model,
        "choices" => [%{"index" => 0, "delta" => %{}, "finish_reason" => "tool_calls"}]
      }
    ]

    sse = chunks |> Enum.map(fn d -> "data: #{Jason.encode!(d)}\n\n" end) |> Enum.join()
    sse <> "data: [DONE]\n\n"
  end

  def anthropic_chat_fixture(opts \\ []) do
    id = Keyword.get(opts, :id, "msg_test123")
    model = Keyword.get(opts, :model, "claude-sonnet-4-20250514")
    content = Keyword.get(opts, :content, "Hello! How can I help you?")
    stop_reason = Keyword.get(opts, :stop_reason, "end_turn")
    tool_use = Keyword.get(opts, :tool_use, nil)

    content_blocks = if content, do: [%{"type" => "text", "text" => content}], else: []
    content_blocks = if tool_use, do: content_blocks ++ [tool_use], else: content_blocks

    %{
      "id" => id,
      "type" => "message",
      "role" => "assistant",
      "model" => model,
      "content" => content_blocks,
      "stop_reason" => stop_reason,
      "stop_sequence" => nil,
      "usage" => %{"input_tokens" => 10, "output_tokens" => 20}
    }
    |> Jason.encode!()
  end

  def anthropic_stream_fixture(opts \\ []) do
    chunks = Keyword.get(opts, :chunks, ["Hello", " there", "!"])
    model = Keyword.get(opts, :model, "claude-sonnet-4-20250514")
    id = Keyword.get(opts, :id, "msg_stream123")

    start_ev = "event: message_start\n"

    start_ev <>
      "data: #{Jason.encode!(%{"type" => "message_start", "message" => %{"id" => id, "type" => "message", "role" => "assistant", "model" => model, "content" => [], "stop_reason" => nil, "usage" => %{"input_tokens" => 10, "output_tokens" => 0}}})}\n\n" <>
      "event: content_block_start\n" <>
      "data: #{Jason.encode!(%{"type" => "content_block_start", "index" => 0, "content_block" => %{"type" => "text", "text" => ""}})}\n\n" <>
      (chunks
       |> Enum.map(fn t ->
         "event: content_block_delta\ndata: #{Jason.encode!(%{"type" => "content_block_delta", "index" => 0, "delta" => %{"type" => "text_delta", "text" => t}})}\n\n"
       end)
       |> Enum.join()) <>
      "event: content_block_stop\ndata: #{Jason.encode!(%{"type" => "content_block_stop", "index" => 0})}\n\n" <>
      "event: message_delta\ndata: #{Jason.encode!(%{"type" => "message_delta", "delta" => %{"stop_reason" => "end_turn"}, "usage" => %{"output_tokens" => length(chunks)}})}\n\n" <>
      "event: message_stop\ndata: #{Jason.encode!(%{"type" => "message_stop"})}\n\n"
  end
  # ── Responses API Fixtures (chatgpt_oauth) ───────────────────────────────────────────────────

  def responses_api_chat_fixture(opts \\ []) do
    id = Keyword.get(opts, :id, "resp_test123")
    model = Keyword.get(opts, :model, "gpt-5.3-codex")
    content = Keyword.get(opts, :content, "Hello! How can I help you?")
    function_call = Keyword.get(opts, :function_call, nil)

    output_items = []

    output_items =
      if content do
        output_items ++
          [
            %{
              "type" => "message",
              "id" => "msg_test",
              "role" => "assistant",
              "content" => [%{"type" => "output_text", "text" => content, "annotations" => []}]
            }
          ]
      else
        output_items
      end

    output_items =
      if function_call do
        output_items ++ [function_call]
      else
        output_items
      end

    %{
      "id" => id,
      "object" => "response",
      "model" => model,
      "output" => output_items,
      "status" => "completed",
      "usage" => %{"input_tokens" => 10, "output_tokens" => 20, "total_tokens" => 30}
    }
    |> Jason.encode!()
  end

  def responses_api_stream_fixture(opts \\ []) do
    chunks = Keyword.get(opts, :chunks, ["Hello", " there", "!"])
    model = Keyword.get(opts, :model, "gpt-5.3-codex")
    id = Keyword.get(opts, :id, "resp_stream123")

    nl = "\n"
    nn = "\n\n"

    "event: response.created" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.created",
        "response" => %{
          "id" => id,
          "object" => "response",
          "model" => model,
          "status" => "in_progress",
          "output" => [],
          "usage" => %{}
        }
      }) <>
      nn <>
      "event: response.output_item.added" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.output_item.added",
        "output_index" => 0,
        "item" => %{
          "type" => "message",
          "id" => "msg_" <> id,
          "role" => "assistant",
          "content" => []
        }
      }) <>
      nn <>
      "event: response.content_part.added" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.content_part.added",
        "output_index" => 0,
        "content_index" => 0,
        "part" => %{"type" => "output_text", "text" => "", "annotations" => []}
      }) <>
      nn <>
      (chunks
       |> Enum.map(fn t ->
         "event: response.output_text.delta" <>
           nl <>
           "data: " <>
           Jason.encode!(%{
             "type" => "response.output_text.delta",
             "output_index" => 0,
             "content_index" => 0,
             "delta" => t
           }) <> nn
       end)
       |> Enum.join()) <>
      "event: response.output_text.done" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.output_text.done",
        "output_index" => 0,
        "content_index" => 0,
        "text" => Enum.join(chunks)
      }) <>
      nn <>
      "event: response.output_item.done" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.output_item.done",
        "output_index" => 0,
        "item" => %{
          "type" => "message",
          "id" => "msg_" <> id,
          "role" => "assistant",
          "content" => [%{"type" => "output_text", "text" => Enum.join(chunks)}]
        }
      }) <>
      nn <>
      "event: response.completed" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.completed",
        "response" => %{
          "id" => id,
          "object" => "response",
          "model" => model,
          "status" => "completed",
          "output" => [
            %{
              "type" => "message",
              "id" => "msg_" <> id,
              "role" => "assistant",
              "content" => [%{"type" => "output_text", "text" => Enum.join(chunks)}]
            }
          ],
          "usage" => %{
            "input_tokens" => 10,
            "output_tokens" => length(chunks),
            "total_tokens" => 10 + length(chunks)
          }
        }
      }) <> nn
  end

  def responses_api_tool_stream_fixture(opts \\ []) do
    id = Keyword.get(opts, :id, "resp_tool123")
    model = Keyword.get(opts, :model, "gpt-5.3-codex")
    tool_name = Keyword.get(opts, :tool_name, "get_weather")
    call_id = Keyword.get(opts, :call_id, "call_abc123")
    arguments = Keyword.get(opts, :arguments, ~s({"location": "Boston"}))

    nl = "\n"
    nn = "\n\n"

    "event: response.created" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.created",
        "response" => %{
          "id" => id,
          "object" => "response",
          "model" => model,
          "status" => "in_progress",
          "output" => [],
          "usage" => %{}
        }
      }) <>
      nn <>
      "event: response.output_item.added" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.output_item.added",
        "output_index" => 0,
        "item" => %{
          "type" => "function_call",
          "id" => "fc_" <> id,
          "call_id" => call_id,
          "name" => tool_name,
          "arguments" => ""
        }
      }) <>
      nn <>
      "event: response.function_call_arguments.delta" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.function_call_arguments.delta",
        "output_index" => 0,
        "delta" => arguments
      }) <>
      nn <>
      "event: response.function_call_arguments.done" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.function_call_arguments.done",
        "output_index" => 0,
        "arguments" => arguments
      }) <>
      nn <>
      "event: response.output_item.done" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.output_item.done",
        "output_index" => 0,
        "item" => %{
          "type" => "function_call",
          "id" => "fc_" <> id,
          "call_id" => call_id,
          "name" => tool_name,
          "arguments" => arguments
        }
      }) <>
      nn <>
      "event: response.completed" <>
      nl <>
      "data: " <>
      Jason.encode!(%{
        "type" => "response.completed",
        "response" => %{
          "id" => id,
          "object" => "response",
          "model" => model,
          "status" => "completed",
          "output" => [
            %{
              "type" => "function_call",
              "id" => "fc_" <> id,
              "call_id" => call_id,
              "name" => tool_name,
              "arguments" => arguments
            }
          ],
          "usage" => %{"input_tokens" => 10, "output_tokens" => 50, "total_tokens" => 60}
        }
      }) <> nn
  end

  def anthropic_tool_stream_fixture(opts \\ []) do
    id = Keyword.get(opts, :id, "msg_tool123")
    model = Keyword.get(opts, :model, "claude-sonnet-4-20250514")
    tool_name = Keyword.get(opts, :tool_name, "get_weather")
    tool_use_id = Keyword.get(opts, :tool_use_id, "toolu_abc123")
    input_json = Keyword.get(opts, :input_json, ~s({"location": "Boston"}))

    "event: message_start\ndata: #{Jason.encode!(%{"type" => "message_start", "message" => %{"id" => id, "type" => "message", "role" => "assistant", "model" => model, "content" => [], "stop_reason" => nil, "usage" => %{"input_tokens" => 10, "output_tokens" => 0}}})}\n\n" <>
      "event: content_block_start\ndata: #{Jason.encode!(%{"type" => "content_block_start", "index" => 0, "content_block" => %{"type" => "tool_use", "id" => tool_use_id, "name" => tool_name, "input" => %{}}})}\n\n" <>
      "event: content_block_delta\ndata: #{Jason.encode!(%{"type" => "content_block_delta", "index" => 0, "delta" => %{"type" => "input_json_delta", "partial_json" => input_json}})}\n\n" <>
      "event: content_block_stop\ndata: #{Jason.encode!(%{"type" => "content_block_stop", "index" => 0})}\n\n" <>
      "event: message_delta\ndata: #{Jason.encode!(%{"type" => "message_delta", "delta" => %{"stop_reason" => "tool_use"}, "usage" => %{"output_tokens" => 50}})}\n\n" <>
      "event: message_stop\ndata: #{Jason.encode!(%{"type" => "message_stop"})}\n\n"
  end
end
