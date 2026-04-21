defmodule CodePuppyControl.CLI.SlashCommands.Commands.AddModel do
  @moduledoc """
  Add Model slash command: /add_model.

  Interactive flow for browsing providers and models from the models.dev
  catalog, then persisting the selected model into extra_models.json.

  Pragmatic first version: text-based selection (no full TUI split-panel).
  The flow is:

    1. Load providers from ModelsDevParser.Registry
    2. Display numbered provider list; user picks one
    3. Display numbered model list for that provider; user picks one
    4. Build Code Puppy config and persist to extra_models.json
    5. Reload ModelRegistry so the new model is immediately available

  Ported from Python `code_puppy/command_line/add_model_menu.py`.
  """

  alias CodePuppyControl.ModelsDevParser
  alias CodePuppyControl.ModelsDevParser.ModelInfo
  alias CodePuppyControl.ModelsDevParser.ProviderInfo
  alias CodePuppyControl.CLI.SlashCommands.Commands.AddModelPersistence

  # Providers that use non-OpenAI-compatible APIs or require special auth.
  @unsupported_providers %{
    "amazon-bedrock" => "Requires AWS SigV4 authentication",
    "google-vertex" => "Requires GCP service account authentication",
    "google-vertex-anthropic" => "Requires GCP service account authentication",
    "cloudflare-workers-ai" => "Requires account ID in URL path",
    "vercel" => "Vercel AI Gateway - not yet supported",
    "v0" => "Vercel v0 - not yet supported",
    "ollama-cloud" => "Requires user-specific Ollama instance URL"
  }

  # Hardcoded OpenAI-compatible endpoints for providers that have dedicated
  # SDKs but work fine with custom_openai.
  @provider_endpoints %{
    "xai" => "https://api.x.ai/v1",
    "cohere" => "https://api.cohere.com/compatibility/v1",
    "groq" => "https://api.groq.com/openai/v1",
    "mistral" => "https://api.mistral.ai/v1",
    "togetherai" => "https://api.together.xyz/v1",
    "perplexity" => "https://api.perplexity.ai",
    "deepinfra" => "https://api.deepinfra.com/v1/openai",
    "aihubmix" => "https://aihubmix.com/v1"
  }

  # Map provider IDs to Code Puppy model types.
  @provider_type_map %{
    "openai" => "openai",
    "anthropic" => "anthropic",
    "google" => "gemini",
    "google-vertex" => "gemini",
    "mistral" => "custom_openai",
    "groq" => "custom_openai",
    "together-ai" => "custom_openai",
    "fireworks" => "custom_openai",
    "deepseek" => "custom_openai",
    "openrouter" => "custom_openai",
    "cerebras" => "cerebras",
    "cohere" => "custom_openai",
    "perplexity" => "custom_openai",
    "minimax" => "custom_anthropic"
  }

  # Map provider IDs to persisted provider identity strings.
  @provider_identity_map %{
    "openai" => "openai",
    "anthropic" => "anthropic",
    "google" => "google",
    "google-vertex" => "google",
    "mistral" => "mistral",
    "groq" => "groq",
    "together-ai" => "together_ai",
    "fireworks" => "fireworks",
    "deepseek" => "deepseek",
    "openrouter" => "openrouter",
    "cerebras" => "cerebras",
    "cohere" => "cohere",
    "perplexity" => "perplexity",
    "minimax" => "minimax",
    "azure-openai" => "azure_openai",
    "xai" => "xai"
  }

  @page_size 15

  @doc """
  Handles `/add_model` — interactive model browser.

  Returns `{:continue, state}` always (does not halt the REPL).
  """
  @spec handle_add_model(String.t(), any()) :: {:continue, any()}
  def handle_add_model(_line, state) do
    run_interactive()
    {:continue, state}
  end

  # ── Public helpers (for testability) ─────────────────────────────────────

  @doc """
  Derive the persisted provider identity for a provider.
  Falls back to replacing hyphens with underscores.
  """
  @spec derive_provider_identity(ProviderInfo.t()) :: String.t()
  def derive_provider_identity(%ProviderInfo{id: id}) do
    Map.get(@provider_identity_map, id, String.replace(id, "-", "_"))
  end

  @doc """
  Check whether a provider is in the unsupported list.
  """
  @spec unsupported_provider?(String.t()) :: boolean()
  def unsupported_provider?(provider_id) do
    Map.has_key?(@unsupported_providers, provider_id)
  end

  @doc """
  Get the reason a provider is unsupported, or nil.
  """
  @spec unsupported_reason(String.t()) :: String.t() | nil
  def unsupported_reason(provider_id) do
    Map.get(@unsupported_providers, provider_id)
  end

  @doc """
  Build a Code Puppy model config map from a ModelInfo and ProviderInfo.

  This mirrors Python's `_build_model_config()` with the same type mapping,
  endpoint derivation, and supported_settings logic.
  """
  @spec build_model_config(ModelInfo.t(), ProviderInfo.t()) :: map()
  def build_model_config(%ModelInfo{} = model, %ProviderInfo{} = provider) do
    model_type = Map.get(@provider_type_map, provider.id, "custom_openai")

    model_name =
      if provider.id == "kimi-for-coding" do
        "kimi-for-coding"
      else
        model.model_id
      end

    config = %{
      "type" => model_type,
      "provider" => derive_provider_identity(provider),
      "name" => model_name
    }

    # Add custom endpoint for non-standard providers
    config =
      if model_type == "custom_openai" do
        add_custom_endpoint(config, provider)
      else
        config
      end

    # Special handling for minimax: uses custom_anthropic but needs endpoint
    config =
      if provider.id == "minimax" and provider.api not in [nil, ""] do
        api_url = String.trim_trailing(provider.api, "/v1")
        api_key_env = if provider.env != [], do: "$#{hd(provider.env)}", else: "$API_KEY"
        Map.put(config, "custom_endpoint", %{"url" => api_url, "api_key" => api_key_env})
      else
        config
      end

    # Add context length
    config =
      if model.context_length > 0 do
        Map.put(config, "context_length", model.context_length)
      else
        config
      end

    # Add supported settings
    Map.put(config, "supported_settings", supported_settings_for(model_type, model))
  end

  @doc """
  Run the interactive flow programmatically (for testing without IO).
  Returns `{:ok, model_key}` on success, or `{:error, reason}` / `:cancelled`.
  """
  @spec run_with_inputs([String.t()]) :: {:ok, String.t()} | {:error, String.t()} | :cancelled
  def run_with_inputs(inputs) do
    case get_providers_list() do
      {:error, reason} ->
        {:error, reason}

      {:ok, providers} ->
        # First input: provider selection
        case inputs do
          [] -> :cancelled
          [provider_input | rest] ->
            case parse_selection(provider_input, length(providers)) do
              {:ok, provider_idx} ->
                provider = Enum.at(providers, provider_idx)

                if unsupported_provider?(provider.id) do
                  {:error, "Cannot add model from #{provider.name}: #{unsupported_reason(provider.id)}"}
                else
                  case get_models_list(provider.id) do
                    {:error, reason} -> {:error, reason}
                    {:ok, models} ->
                      case rest do
                        [] -> :cancelled
                        [model_input | _rest] ->
                          case parse_selection(model_input, length(models)) do
                            {:ok, model_idx} ->
                              model = Enum.at(models, model_idx)
                              add_model_to_config(model, provider)

                            {:error, _} = err ->
                              err
                          end
                      end
                  end
                end

              {:error, _} = err ->
                err
            end
        end
    end
  end

  # ── Private: interactive flow ───────────────────────────────────────────

  defp run_interactive do
    case get_providers_list() do
      {:error, reason} ->
        IO.puts(IO.ANSI.red() <> "    Error loading providers: #{reason}" <> IO.ANSI.reset())

      {:ok, []} ->
        IO.puts(IO.ANSI.yellow() <> "    No providers available." <> IO.ANSI.reset())

      {:ok, providers} ->
        IO.puts("")
        IO.puts(IO.ANSI.bright() <> "    Add Model — Browse providers" <> IO.ANSI.reset())
        IO.puts("")

        browse_providers(providers, 0)
    end
  end

  defp browse_providers(providers, page) do
    total = length(providers)
    total_pages = max(1, ceil(total / @page_size))

    display_providers(providers, page)

    IO.puts("")

    prompt =
      if total_pages > 1 do
        "    Select provider [1-#{total}] (n=next, p=prev, f=filter, q=cancel): "
      else
        "    Select provider [1-#{total}] or q to cancel: "
      end

    IO.write(prompt)

    case IO.gets("") do
      :eof ->
        IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())

      {:error, _} ->
        IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())

      input ->
        handle_provider_input(String.trim(input), providers, page, total_pages)
    end
  end

  defp handle_provider_input(input, providers, page, total_pages) do
    cond do
      input =~ ~r/^[qQ]$/ ->
        IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())

      input == "n" and page + 1 < total_pages ->
        browse_providers(providers, page + 1)

      input == "p" and page > 0 ->
        browse_providers(providers, page - 1)

      String.starts_with?(input, "f ") ->
        query = String.trim_leading(input, "f ")
        filtered = filter_providers(providers, query)

        if filtered == [] do
          IO.puts(IO.ANSI.faint() <> "    No providers match '#{query}'." <> IO.ANSI.reset())
          browse_providers(providers, page)
        else
          IO.puts(IO.ANSI.faint() <> "    Filtered: #{length(filtered)} provider(s) match '#{query}'." <> IO.ANSI.reset())
          browse_providers(filtered, 0)
        end

      true ->
        case parse_selection(input, length(providers)) do
          {:ok, idx} ->
            provider = Enum.at(providers, idx)
            select_model_interactive(provider)

          {:error, reason} ->
            IO.puts(IO.ANSI.red() <> "    Invalid selection: #{reason}" <> IO.ANSI.reset())
            browse_providers(providers, page)
        end
    end
  end

  defp select_model_interactive(provider) do
    if unsupported_provider?(provider.id) do
      reason = unsupported_reason(provider.id)

      IO.puts(
        IO.ANSI.red() <>
          "    Cannot add model from #{provider.name}: #{reason}" <>
          IO.ANSI.reset()
      )

      return_to_menu_hint()
    else
      case get_models_list(provider.id) do
        {:error, reason} ->
          IO.puts(IO.ANSI.red() <> "    Error loading models: #{reason}" <> IO.ANSI.reset())

        {:ok, []} ->
          IO.puts(IO.ANSI.yellow() <> "    No models found for #{provider.name}." <> IO.ANSI.reset())

        {:ok, models} ->
          IO.puts("")
          IO.puts(IO.ANSI.bright() <> "    #{provider.name} — Select model" <> IO.ANSI.reset())
          IO.puts("")

          browse_models(models, provider, 0)
      end
    end
  end

  defp browse_models(models, provider, page) do
    total = length(models)
    total_pages = max(1, ceil(total / @page_size))

    display_models(models, page)

    IO.puts("")

    prompt =
      if total_pages > 1 do
        "    Select model [1-#{total}] (n=next, p=prev, f=filter, q=cancel): "
      else
        "    Select model [1-#{total}] or q to cancel: "
      end

    IO.write(prompt)

    case IO.gets("") do
      :eof ->
        IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())

      {:error, _} ->
        IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())

      input ->
        handle_model_input(String.trim(input), models, provider, page, total_pages)
    end
  end

  defp handle_model_input(input, models, provider, page, total_pages) do
    cond do
      input =~ ~r/^[qQ]$/ ->
        IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())

      input == "n" and page + 1 < total_pages ->
        browse_models(models, provider, page + 1)

      input == "p" and page > 0 ->
        browse_models(models, provider, page - 1)

      String.starts_with?(input, "f ") ->
        query = String.trim_leading(input, "f ")
        filtered = filter_models(models, query)

        if filtered == [] do
          IO.puts(IO.ANSI.faint() <> "    No models match '#{query}'." <> IO.ANSI.reset())
          browse_models(models, provider, page)
        else
          IO.puts(IO.ANSI.faint() <> "    Filtered: #{length(filtered)} model(s) match '#{query}'." <> IO.ANSI.reset())
          browse_models(filtered, provider, 0)
        end

      true ->
        case parse_selection(input, length(models)) do
          {:ok, idx} ->
            model = Enum.at(models, idx)
            execute_add_model(model, provider)

          {:error, reason} ->
            IO.puts(IO.ANSI.red() <> "    Invalid selection: #{reason}" <> IO.ANSI.reset())
            browse_models(models, provider, page)
        end
    end
  end

  @doc """
  Filter a list of providers by a query string (case-insensitive).
  Matches against provider name and id.
  """
  @spec filter_providers([ProviderInfo.t()], String.t()) :: [ProviderInfo.t()]
  def filter_providers(providers, query) do
    q = String.downcase(query)
    Enum.filter(providers, fn p ->
      String.contains?(String.downcase(p.name), q) or
        String.contains?(String.downcase(p.id), q)
    end)
  end

  @doc """
  Filter a list of models by a query string (case-insensitive).
  Matches against model name and model_id.
  """
  @spec filter_models([ModelInfo.t()], String.t()) :: [ModelInfo.t()]
  def filter_models(models, query) do
    q = String.downcase(query)
    Enum.filter(models, fn m ->
      String.contains?(String.downcase(m.name), q) or
        String.contains?(String.downcase(m.model_id), q)
    end)
  end

  defp execute_add_model(model, provider) do
    # Warn about non-tool-calling models
    if not model.tool_call do
      IO.puts("")

      IO.puts(
        IO.ANSI.yellow() <>
          "    ⚠️  #{model.name} does NOT support tool calling!" <>
          IO.ANSI.reset()
      )

      IO.puts(
        IO.ANSI.yellow() <>
          "    This model won't be able to edit files, run commands, or use tools." <>
          IO.ANSI.reset()
      )

      IO.write("    Add anyway? (y/N): ")

      case IO.gets("") do
        resp when is_binary(resp) ->
          if String.trim(resp) =~ ~r/^[yY]/ do
            do_add_model(model, provider)
          else
            IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())
          end

        _ ->
          IO.puts(IO.ANSI.yellow() <> "    Cancelled." <> IO.ANSI.reset())
      end
    else
      do_add_model(model, provider)
    end
  end

  defp do_add_model(model, provider) do
    case add_model_to_config(model, provider) do
      {:ok, model_key} ->
        IO.puts("")

        IO.puts(
          IO.ANSI.green() <>
            "    ✅ Added #{model_key} to extra_models.json" <>
            IO.ANSI.reset()
        )

        # Reload ModelRegistry so the new model is immediately available
        case CodePuppyControl.ModelRegistry.reload() do
          :ok ->
            IO.puts(
              IO.ANSI.faint() <>
                "    Model registry reloaded." <>
                IO.ANSI.reset()
            )

          {:error, reason} ->
            IO.puts(
              IO.ANSI.yellow() <>
                "    Warning: registry reload failed: #{inspect(reason)}" <>
                IO.ANSI.reset()
            )
        end

        IO.puts("")

      {:error, :already_exists} ->
        IO.puts("")
        IO.puts(IO.ANSI.cyan() <> "    Model already in extra_models.json." <> IO.ANSI.reset())
        IO.puts("")

      {:error, reason} ->
        IO.puts("")

        IO.puts(
          IO.ANSI.red() <>
            "    ❌ Error adding model: #{reason}" <>
            IO.ANSI.reset()
        )

        IO.puts("")
    end
  end

  # ── Private: display helpers ─────────────────────────────────────────────

  defp display_providers(providers, page) do
    total = length(providers)
    total_pages = max(1, ceil(total / @page_size))
    start_idx = page * @page_size

    Enum.slice(providers, start_idx, @page_size)
    |> Enum.with_index(fn provider, i ->
      num = i + start_idx + 1
      unsup = unsupported_provider?(provider.id)
      count = ProviderInfo.model_count(provider)

      line =
        if unsup do
          "    #{num}. #{provider.name} (#{count} models) ⚠️"
        else
          "    #{num}. #{provider.name} (#{count} models)"
        end

      if unsup do
        IO.puts(IO.ANSI.faint() <> line <> IO.ANSI.reset())
      else
        IO.puts(line)
      end
    end)

    if total_pages > 1 do
      IO.puts(IO.ANSI.faint() <> "    Page #{page + 1}/#{total_pages}" <> IO.ANSI.reset())
    end
  end

  defp display_models(models, page) do
    total = length(models)
    total_pages = max(1, ceil(total / @page_size))
    start_idx = page * @page_size

    Enum.slice(models, start_idx, @page_size)
    |> Enum.with_index(fn model, i ->
      num = i + start_idx + 1

      icons =
        []
        |> maybe_icon(ModelInfo.has_vision?(model), "👁")
        |> maybe_icon(model.tool_call, "🔧")
        |> maybe_icon(model.reasoning, "🧠")

      icon_str = if icons == [], do: "", else: Enum.join(icons, " ") <> " "

      IO.puts("    #{num}. #{icon_str}#{model.name}")
    end)

    if total_pages > 1 do
      IO.puts(IO.ANSI.faint() <> "    Page #{page + 1}/#{total_pages}" <> IO.ANSI.reset())
    end
  end

  defp maybe_icon(icons, true, icon), do: icons ++ [icon]
  defp maybe_icon(icons, false, _icon), do: icons

  defp return_to_menu_hint do
    IO.puts(IO.ANSI.faint() <> "    Use /add_model to browse again." <> IO.ANSI.reset())
  end

  # ── Private: data access ─────────────────────────────────────────────────

  defp get_providers_list do
    case Process.whereis(CodePuppyControl.ModelsDevParser.Registry) do
      nil -> {:error, "ModelsDev registry not started"}
      _pid -> {:ok, ModelsDevParser.get_providers()}
    end
  rescue
    e -> {:error, Exception.message(e)}
  end

  defp get_models_list(provider_id) do
    case Process.whereis(CodePuppyControl.ModelsDevParser.Registry) do
      nil -> {:error, "ModelsDev registry not started"}
      _pid -> {:ok, ModelsDevParser.get_models(ModelsDevParser.Registry, provider_id)}
    end
  rescue
    e -> {:error, Exception.message(e)}
  end

  # ── Private: config building ─────────────────────────────────────────────

  defp add_custom_endpoint(config, provider) do
    api_url =
      cond do
        provider.api not in [nil, ""] -> provider.api
        true -> Map.get(@provider_endpoints, provider.id)
      end

    if api_url do
      api_key_env = if provider.env != [], do: "$#{hd(provider.env)}", else: "$API_KEY"
      Map.put(config, "custom_endpoint", %{"url" => api_url, "api_key" => api_key_env})
    else
      config
    end
  end

  defp supported_settings_for("anthropic", _model) do
    ["temperature", "extended_thinking", "budget_tokens"]
  end

  defp supported_settings_for("openai", %ModelInfo{model_id: model_id}) do
    if String.contains?(model_id, "gpt-5") do
      if String.contains?(model_id, "codex") do
        ["temperature", "top_p", "reasoning_effort"]
      else
        ["temperature", "top_p", "reasoning_effort", "verbosity"]
      end
    else
      ["temperature", "seed", "top_p"]
    end
  end

  defp supported_settings_for(_type, _model) do
    ["temperature", "seed", "top_p"]
  end

  # ── Private: selection parsing ───────────────────────────────────────────

  defp parse_selection(input, max_index) do
    case Integer.parse(String.trim(input)) do
      {n, ""} when n >= 1 and n <= max_index ->
        {:ok, n - 1}

      _ ->
        {:error, "enter a number between 1 and #{max_index}"}
    end
  end

  # ── Private: persistence ─────────────────────────────────────────────────

  defp add_model_to_config(model, provider) do
    config = build_model_config(model, provider)
    model_key = build_model_key(provider, model)
    AddModelPersistence.persist(model_key, config)
  end

  defp build_model_key(provider, model) do
    "#{provider.id}-#{model.model_id}"
    |> String.replace("/", "-")
    |> String.replace(":", "-")
  end
end
