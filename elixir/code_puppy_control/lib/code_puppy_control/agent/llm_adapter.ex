defmodule CodePuppyControl.Agent.LLMAdapter do
  @moduledoc """
  Adapter translating the old `CodePuppyControl.Agent.LLM` behaviour contract
  (used by `Agent.Loop`) into the provider-facing `CodePuppyControl.LLM`
  contract.

  ## Why

  `Agent.Loop` was built against the Agent.LLM behaviour (atom tool names,
  `{:ok, response}` return). `CodePuppyControl.LLM` was built against the
  Finch+provider contract (schema-map tools, `:ok` return with response
  delivered via `{:done, response}` callback event). This module is the single
  place where the two formats cross.

  ## Contracts

  Inbound (from Agent.Loop via `do_llm_stream/2`):
    * messages — list of maps, possibly mixed atom/string keys, possibly
      using `"parts"` format from Agent.State
    * tools — list of atoms from `agent_module.allowed_tools/0`
    * opts — keyword with `:model`, `:system_prompt`
    * callback_fn — Normalizer-wrapped function receiving raw provider events

  Outbound (to CodePuppyControl.LLM):
    * messages — list of `%{role: _, content: _}` (atom keys, flattened
      from "parts" format for v1)
    * tools — list of JSON-Schema function maps per Tool.Registry
    * opts — pass-through
    * callback_fn — wrapped to capture the terminal response for return value
  """

  @behaviour CodePuppyControl.Agent.LLM

  alias CodePuppyControl.LLM
  alias CodePuppyControl.Tool
  alias CodePuppyControl.Tool.Registry

  require Logger

  @impl true
  def stream_chat(messages, tool_names, opts, callback_fn) do
    provider_messages = Enum.map(messages, &to_provider_message/1)
    provider_tools = resolve_tools(tool_names)

    llm_mod = Application.get_env(:code_puppy_control, :llm_adapter_provider, LLM)

    parent = self()
    ref = make_ref()

    # Wrap the callback to capture the final response from {:done, response}.
    #
    # The callback_fn we receive is already Normalizer-wrapped (by
    # do_llm_stream/2), so it accepts raw provider events. We intercept
    # the {:done, response} event before forwarding it, because the Normalizer
    # converts it to {:stream, %Done{}} which loses the response content.
    wrapped_callback = fn
      {:done, response} = event ->
        send(parent, {:llm_adapter_done, ref, response})
        callback_fn.(event)

      event ->
        callback_fn.(event)
    end

    case llm_mod.stream_chat(provider_messages, provider_tools, opts, wrapped_callback) do
      :ok ->
        # LLM.stream_chat returns :ok after all streaming is complete.
        # The {:done, response} callback has already fired, so the message
        # is in our mailbox.
        receive do
          {:llm_adapter_done, ^ref, response} ->
            {:ok, adapter_response(response)}
        after
          5_000 ->
            Logger.warning("LLMAdapter: timed out waiting for {:done, response}")
            {:error, :adapter_timeout}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  # ── Response conversion ──────────────────────────────────────────────────

  # Convert provider response to the Agent.LLM contract return format.
  # Provider uses :content and :tool_calls with %{id, name, arguments}.
  # Agent.LLM contract expects %{text: ..., tool_calls: [%{id, name, arguments}]}.
  defp adapter_response(response) when is_map(response) do
    %{
      text: response[:content] || response["content"] || "",
      tool_calls: normalize_tool_calls(response[:tool_calls] || response["tool_calls"] || [])
    }
  end

  defp adapter_response(_), do: %{text: "", tool_calls: []}

  defp normalize_tool_calls(calls) when is_list(calls) do
    Enum.map(calls, &normalize_tool_call/1)
  end

  defp normalize_tool_call(%{id: id, name: name, arguments: args}) do
    %{id: id || "", name: name, arguments: args}
  end

  defp normalize_tool_call(%{"id" => id, "name" => name, "arguments" => args}) do
    %{id: id || "", name: name, arguments: args}
  end

  defp normalize_tool_call(other), do: other

  # ── Message conversion ───────────────────────────────────────────────────

  # Prompt Toolkit "parts" format (string-keyed) — flatten to text.
  # Agent.State stores: %{"role" => "user", "parts" => [%{"type" => "text", "text" => "..."}]}
  defp to_provider_message(%{"role" => role, "parts" => parts} = msg) when is_list(parts) do
    text =
      parts
      |> Enum.map(fn
        %{"type" => "text", "text" => t} -> t
        %{type: :text, text: t} -> t
        other when is_binary(other) -> other
        _ -> ""
      end)
      |> Enum.join("")

    base = %{role: role, content: text}
    maybe_put(base, :tool_call_id, msg["tool_call_id"] || msg[:tool_call_id])
  end

  # String-keyed content (already in provider shape or close to it)
  defp to_provider_message(%{"role" => role, "content" => content} = msg) do
    base = %{role: role, content: content}
    maybe_put(base, :tool_call_id, msg["tool_call_id"] || msg[:tool_call_id])
  end

  # Atom-keyed content (from Agent.Loop internals)
  defp to_provider_message(%{role: role, content: content} = msg) do
    base = %{role: to_string(role), content: content}
    maybe_put(base, :tool_call_id, msg[:tool_call_id] || msg["tool_call_id"])
  end

  # Fallback: try to coerce
  defp to_provider_message(msg) do
    Logger.warning("LLMAdapter: unknown message shape, passing through: #{inspect(msg)}")
    msg
  end

  defp maybe_put(map, _key, nil), do: map
  defp maybe_put(map, key, value), do: Map.put(map, key, value)

  # ── Tool conversion ──────────────────────────────────────────────────────

  # Resolve atom tool names into JSON-Schema function maps.
  # Uses Tool.Registry.lookup/1 + Tool.to_llm_format/1.
  # If Registry is unavailable or lookup fails, return empty list
  # (agent runs without tools rather than crashing).
  defp resolve_tools(tool_names) when is_list(tool_names) do
    tool_names
    |> Enum.map(&resolve_single_tool/1)
    |> Enum.reject(&is_nil/1)
  rescue
    _ -> []
  end

  defp resolve_single_tool(name) when is_atom(name) do
    try do
      case Registry.lookup(name) do
        {:ok, module} ->
          Tool.to_llm_format(module)

        :error ->
          Logger.debug("LLMAdapter: tool #{inspect(name)} not found in Registry, skipping")
          nil
      end
    rescue
      _ -> nil
    end
  end

  defp resolve_single_tool(_), do: nil
end
