defmodule Mana.Plugins.OllamaSetup do
  @moduledoc """
  Plugin that auto-detects Ollama on startup and registers discovered models.

  On startup, checks if Ollama is running at `localhost:11434/api/tags`.
  If available, auto-registers discovered models with `Mana.Models.Registry`.

  Also provides the `/ollama-setup` command for manual model registration.

  ## Hooks Registered

  - `:startup` — Auto-detect Ollama and register models
  - `:custom_command` — Handle `/ollama-setup` slash commands
  - `:custom_command_help` — Advertise in `/help` menu

  ## Configuration

      config :mana, Mana.Plugin.Manager,
        plugin_configs: %{
          Mana.Plugins.OllamaSetup => %{
            ollama_host: "http://localhost:11434",  # Ollama server URL
            auto_register: true                      # Auto-register on startup
          }
        }

  ## Example

      /ollama-setup           # Show discovered Ollama models
      /ollama-setup llama3.2  # Register a specific model
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  @default_host "http://localhost:11434"
  @tags_endpoint "/api/tags"
  @ollama_provider "ollama"

  # ── Plugin Behaviour ──────────────────────────────────────────────────────

  @impl true
  def name, do: "ollama_setup"

  @impl true
  def init(config) do
    host = Map.get(config, :ollama_host, @default_host)
    auto_register = Map.get(config, :auto_register, true)

    {:ok, %{host: host, auto_register: auto_register, config: config}}
  end

  @impl true
  def hooks do
    [
      {:startup, &__MODULE__.on_startup/0},
      {:custom_command, &__MODULE__.handle_command/2},
      {:custom_command_help, &__MODULE__.command_help/0}
    ]
  end

  @impl true
  def terminate, do: :ok

  # ── Startup Hook ──────────────────────────────────────────────────────────

  @doc """
  Checks if Ollama is running and auto-registers discovered models.

  Called during application startup. Makes an HTTP GET to the Ollama
  tags endpoint. If Ollama is available, registers each model with
  `Mana.Models.Registry`.
  """
  @spec on_startup() :: :ok
  def on_startup do
    case fetch_ollama_models() do
      {:ok, models} when is_list(models) and models != [] ->
        Logger.info("[OllamaSetup] Discovered #{length(models)} Ollama model(s)")

        Enum.each(models, fn model ->
          register_model_with_registry(model)
        end)

        :ok

      {:ok, []} ->
        Logger.info("[OllamaSetup] Ollama is running but no models found")
        :ok

      {:error, :not_available} ->
        Logger.debug("[OllamaSetup] Ollama not available — skipping auto-registration")
        :ok

      {:error, reason} ->
        Logger.warning("[OllamaSetup] Failed to query Ollama: #{inspect(reason)}")
        :ok
    end
  rescue
    e ->
      Logger.warning("[OllamaSetup] Startup error: #{inspect(e)}")
      :ok
  end

  # ── Custom Command Handler ────────────────────────────────────────────────

  @doc """
  Handles `/ollama-setup` slash commands.

  - `/ollama-setup` — Show discovered models
  - `/ollama-setup <model>` — Register a specific model
  """
  @spec handle_command(String.t(), String.t()) :: {:ok, String.t()} | nil
  def handle_command(command, "ollama-setup") do
    tokens = String.split(command, ~r/\s+/, trim: true)
    model_name = if length(tokens) > 1, do: Enum.at(tokens, 1), else: nil

    result =
      case model_name do
        nil -> list_models()
        name -> register_specific_model(name)
      end

    {:ok, result}
  end

  def handle_command(_command, _name), do: nil

  # ── Command Help ──────────────────────────────────────────────────────────

  @doc """
  Returns help entry for `/ollama-setup`.
  """
  @spec command_help() :: [{String.t(), String.t()}]
  def command_help do
    [
      {"ollama-setup", "Auto-detect Ollama models or register a specific model"}
    ]
  end

  # ── Ollama API ────────────────────────────────────────────────────────────

  @doc """
  Fetches available models from the Ollama API.

  Returns `{:ok, models_list}` on success, `{:error, reason}` on failure.
  """
  @spec fetch_ollama_models() :: {:ok, [map()]} | {:error, term()}
  def fetch_ollama_models do
    url = ollama_host() <> @tags_endpoint

    case :httpc.request(:get, {to_charlist(url), []}, [{:timeout, 3000}], []) do
      {:ok, {{_version, 200, _reason}, _headers, body}} ->
        case Jason.decode(to_string(body)) do
          {:ok, %{"models" => models}} when is_list(models) -> {:ok, models}
          {:ok, _} -> {:ok, []}
          {:error, _} = err -> err
        end

      {:ok, {{_version, status, _reason}, _headers, _body}} ->
        {:error, {:http_error, status}}

      {:error, {:failed_connect, _}} ->
        {:error, :not_available}

      {:error, reason} ->
        {:error, reason}
    end
  rescue
    _ -> {:error, :not_available}
  end

  # ── Model Registration ────────────────────────────────────────────────────

  defp register_model_with_registry(%{"name" => name} = model) do
    config = build_model_config(model)
    Mana.Models.Registry.register_model(name, config)
    Logger.info("[OllamaSetup] Registered model: #{name}")
  end

  defp register_model_with_registry(_), do: :ok

  defp build_model_config(model) do
    %{
      "provider" => @ollama_provider,
      "supports_tools" => true,
      "supports_vision" => Map.get(model, "details", %{}) |> Map.get("families", []) |> Enum.member?("clip"),
      "size" => Map.get(model, "size"),
      "modified_at" => Map.get(model, "modified_at")
    }
  end

  # ── Command Sub-handlers ──────────────────────────────────────────────────

  defp list_models do
    case fetch_ollama_models() do
      {:ok, []} ->
        "🦙 Ollama is running but has no models.\nPull one with: ollama pull llama3.2"

      {:ok, models} ->
        lines = ["🦙 Ollama models (#{length(models)} available):\n"]

        lines =
          lines ++
            Enum.map(models, fn model ->
              name = Map.get(model, "name", "unknown")
              size = format_model_size(Map.get(model, "size"))
              "  • #{String.pad_trailing(name, 30)} #{size}"
            end)

        lines = lines ++ ["\nUse: /ollama-setup <model_name> to register with Mana"]
        Enum.join(lines, "\n")

      {:error, :not_available} ->
        "🦙 Ollama is not running. Start it with: ollama serve"

      {:error, reason} ->
        "🦙 Error contacting Ollama: #{inspect(reason)}"
    end
  end

  defp register_specific_model(name) do
    case fetch_ollama_models() do
      {:ok, models} ->
        case Enum.find(models, fn m -> Map.get(m, "name") == name end) do
          nil ->
            "Model '#{name}' not found in Ollama. Available:\n" <>
              Enum.map_join(models, "\n", fn m -> "  • #{Map.get(m, "name", "?")}" end)

          model ->
            register_model_with_registry(model)
            "✅ Registered '#{name}' with Mana model registry"
        end

      {:error, :not_available} ->
        "🦙 Ollama is not running. Start it with: ollama serve"

      {:error, reason} ->
        "Error: #{inspect(reason)}"
    end
  end

  defp format_model_size(nil), do: ""
  defp format_model_size(bytes) when is_integer(bytes), do: "#{div(bytes, 1_000_000)}MB"
  defp format_model_size(_), do: ""

  defp ollama_host do
    # Allow override from state when called in hook context
    Application.get_env(:mana, __MODULE__, [])
    |> Keyword.get(:ollama_host, @default_host)
  end
end
