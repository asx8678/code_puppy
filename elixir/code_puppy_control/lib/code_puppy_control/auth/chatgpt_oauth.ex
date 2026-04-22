defmodule CodePuppyControl.Auth.ChatGPTOAuth do
  @moduledoc """
  ChatGPT OAuth core configuration and model management.

  Port of the Python chatgpt_oauth/config.py and chatgpt_oauth/utils.py
  modules. Provides OAuth endpoint config, token persistence, model fetching
  from the ChatGPT Codex API, and config file management for model overlays.

  All file writes go through Isolation.safe_write!/2 per ADR-003.
  """

  require Logger

  alias CodePuppyControl.Config.{Isolation, Paths}

  # ── OAuth endpoint configuration ────────────────────────────────────────

  @issuer "https://auth.openai.com"
  @auth_url "https://auth.openai.com/oauth/authorize"
  @token_url "https://auth.openai.com/oauth/token"
  @api_base_url "https://chatgpt.com/backend-api/codex"

  # ── OAuth client configuration ──────────────────────────────────────────

  @client_id System.get_env("CHATGPT_OAUTH_CLIENT_ID", "app_EMoamEEZ73f0CkXaXp7hrann")
  @scope "openid profile email offline_access"
  @redirect_host "http://localhost"
  @redirect_path "auth/callback"
  @required_port 1455
  @callback_timeout 120

  # ── Model configuration ────────────────────────────────────────────────

  @prefix "chatgpt-"
  @default_context_length 272_000
  @api_key_env_var "CHATGPT_OAUTH_API_KEY"
  @client_version "0.72.0"
  @originator "codex_cli_rs"

  @doc "Returns the full OAuth configuration as a map."
  @spec config() :: map()
  def config do
    %{
      issuer: @issuer,
      auth_url: @auth_url,
      token_url: @token_url,
      api_base_url: @api_base_url,
      client_id: @client_id,
      scope: @scope,
      redirect_host: @redirect_host,
      redirect_path: @redirect_path,
      required_port: @required_port,
      callback_timeout: @callback_timeout,
      prefix: @prefix,
      default_context_length: @default_context_length,
      api_key_env_var: @api_key_env_var,
      client_version: @client_version,
      originator: @originator
    }
  end

  # ── Path helpers ───────────────────────────────────────────────────────

  @doc "Path to the auth directory under the Elixir home."
  @spec auth_dir() :: String.t()
  def auth_dir, do: Path.join(Paths.home_dir(), "auth")

  @doc "Path to the OAuth token storage file (chatgpt_oauth.json)."
  @spec token_storage_path() :: String.t()
  def token_storage_path, do: Path.join(auth_dir(), "chatgpt_oauth.json")

  @doc "Path to the ChatGPT models overlay file (chatgpt_models.json)."
  @spec chatgpt_models_path() :: String.t()
  def chatgpt_models_path, do: Paths.chatgpt_models_file()

  # ── Token persistence ──────────────────────────────────────────────────

  @doc "Load stored OAuth tokens from disk. Returns nil if absent or corrupt."
  @spec load_tokens() :: map() | nil
  def load_tokens do
    path = token_storage_path()
    with {:ok, data} <- File.read(path),
         {:ok, decoded} <- Jason.decode(data),
         do: decoded
  end

  @doc "Save OAuth tokens to disk via Isolation.safe_write!/2 with 0o600 perms."
  @spec save_tokens(map()) :: :ok
  def save_tokens(tokens) when is_map(tokens) do
    path = token_storage_path()
    Isolation.safe_mkdir_p!(Path.dirname(path))
    Isolation.safe_write!(path, Jason.encode!(tokens, pretty: true))
    File.chmod(path, 0o600)
    :ok
  end

  def save_tokens(_), do: raise(ArgumentError, "tokens must be a map")

  @doc "Remove stored OAuth tokens from disk. Returns :ok even if absent."
  @spec clear_tokens() :: :ok
  def clear_tokens do
    path = token_storage_path()
    if File.exists?(path), do: Isolation.safe_rm!(path)
    :ok
  rescue
    e in Isolation.IsolationViolation ->
      Logger.warning("Cannot clear tokens: " <> Exception.message(e))
      :ok
  end

  # ── Blocked model filtering ───────────────────────────────────────────

  @blocked_models MapSet.new([
                    "gpt-5",
                    "gpt-5-codex",
                    "gpt-5-codex-mini",
                    "gpt-5.1",
                    "gpt-5.1-codex",
                    "gpt-5.1-codex-max",
                    "gpt-5.1-codex-mini",
                    "gpt-5.2",
                    "gpt-5.2-codex",
                    "gpt-4o",
                    "gpt-3.5-turbo",
                    "claude-3-opus"
                  ])

  @default_codex_models [
    "gpt-5.4",
    "gpt-5.3-instant",
    "gpt-5.3-codex-spark",
    "gpt-5.3-codex"
  ]

  @required_codex_models [
    "gpt-5.4",
    "gpt-5.3-instant",
    "gpt-5.3-codex-spark",
    "gpt-5.3-codex"
  ]

  @codex_model_context_lengths %{
    "gpt-5.3-codex-spark" => 131_000,
    "gpt-5.3-instant" => 192_000
  }

  @doc "Check if a model name (bare or prefixed) is blocked."
  @spec blocked_model?(String.t()) :: boolean()
  def blocked_model?(model_name) when is_binary(model_name) do
    bare = strip_prefix(model_name)
    MapSet.member?(@blocked_models, bare) or MapSet.member?(@blocked_models, model_name)
  end

  def blocked_model?(_), do: false

  @doc "Filter a list of model names, dropping blocked ones."
  @spec filter_blocked([String.t()]) :: [String.t()]
  def filter_blocked(models) when is_list(models) do
    Enum.reject(models, &blocked_model?/1)
  end

  @doc "Return the default Codex model list (blocked filtered out)."
  @spec default_models() :: [String.t()]
  def default_models do
    @default_codex_models |> ensure_required_models() |> filter_blocked()
  end

  # ── Model fetching ────────────────────────────────────────────────────

  @doc """
  Fetch available models from the ChatGPT Codex API.

  Sends GET to `{api_base_url}/models` with the `ChatGPT-Account-Id`
  header as required by the Codex backend. Falls back to the default
  model list on any error.
  """
  @spec fetch_models(String.t(), String.t()) :: [String.t()]
  def fetch_models(access_token, account_id) do
    base_url = String.trim_trailing(@api_base_url, "/")
    models_url = base_url <> "/models"

    headers = [
      {"authorization", "Bearer " <> access_token},
      {"chatgpt-account-id", account_id},
      {"user-agent", user_agent_string()},
      {"originator", @originator},
      {"accept", "application/json"}
    ]

    params = [{"client_version", @client_version}]

    case http_get(models_url, headers, params) do
      {:ok, %{"models" => models}} when is_list(models) ->
        model_ids =
          models
          |> Enum.filter(&(&1 != nil))
          |> Enum.map(fn m -> m["slug"] || m["id"] || m["name"] end)
          |> Enum.filter(&(&1 != nil))

        if model_ids != [],
          do: model_ids |> ensure_required_models() |> filter_blocked(),
          else: default_models()

      _ ->
        Logger.info("Models endpoint unavailable, using default model list")
        default_models()
    end
  end

  # ── Model config management ───────────────────────────────────────────

  @doc "Load ChatGPT models from chatgpt_models.json. Blocked entries dropped."
  @spec load_chatgpt_models() :: map()
  def load_chatgpt_models do
    path = chatgpt_models_path()

    with {:ok, data} <- File.read(path),
         {:ok, decoded} <- Jason.decode(data),
         true <- is_map(decoded) do
      Enum.reject(decoded, fn {name, _} -> blocked_model?(name) end) |> Map.new()
    else
      _ -> %{}
    end
  end

  @doc "Save ChatGPT models to chatgpt_models.json via Isolation.safe_write!/2."
  @spec save_chatgpt_models(map()) :: :ok | {:error, term()}
  def save_chatgpt_models(models) when is_map(models) do
    path = chatgpt_models_path()
    Isolation.safe_mkdir_p!(Path.dirname(path))
    Isolation.safe_write!(path, Jason.encode!(models, pretty: true))
    :ok
  rescue
    e ->
      Logger.error("Failed to save ChatGPT models: " <> Exception.message(e))
      {:error, e}
  end

  @doc """
  Add ChatGPT models to chatgpt_models.json.

  Each model gets the `chatgpt-` prefix and metadata including type,
  custom_endpoint, context_length, oauth_source, supported_settings,
  and supports_xhigh_reasoning.
  """
  @spec add_models([String.t()]) :: :ok | {:error, term()}
  def add_models(models) do
    existing = load_chatgpt_models()

    # Clean stale blocked entries from existing config
    cleaned =
      existing
      |> Enum.reject(fn {name, _} -> blocked_model?(name) end)
      |> Map.new()

    filtered = filter_blocked(models)

    updated =
      Enum.reduce(filtered, cleaned, fn model_name, acc ->
        prefixed = @prefix <> model_name
        normalized = String.downcase(model_name)

        supports_xhigh =
          String.contains?(normalized, "codex") or
            String.starts_with?(normalized, "gpt-5.4")

        context_length =
          Map.get(@codex_model_context_lengths, model_name, @default_context_length)

        Map.put(acc, prefixed, %{
          "type" => "chatgpt_oauth",
          "name" => model_name,
          "custom_endpoint" => %{"url" => @api_base_url},
          "context_length" => context_length,
          "oauth_source" => "chatgpt-oauth-plugin",
          "supported_settings" => ["reasoning_effort", "summary", "verbosity"],
          "supports_xhigh_reasoning" => supports_xhigh
        })
      end)

    save_chatgpt_models(updated)
  end

  @doc """
  Remove all ChatGPT OAuth models from chatgpt_models.json.

  Returns count of removed models (identified by `oauth_source`).
  """
  @spec remove_models() :: non_neg_integer()
  def remove_models do
    existing = load_chatgpt_models()

    {to_remove, to_keep} =
      Enum.split_with(existing, fn {_name, cfg} ->
        Map.get(cfg, "oauth_source") == "chatgpt-oauth-plugin"
      end)

    case save_chatgpt_models(Map.new(to_keep)) do
      :ok -> length(to_remove)
      {:error, _} -> 0
    end
  end

  # ── Private helpers ───────────────────────────────────────────────────

  defp strip_prefix(name) do
    prefix_len = String.length(@prefix)

    if String.starts_with?(name, @prefix),
      do: String.slice(name, prefix_len..-1//1),
      else: name
  end

  defp ensure_required_models(models) do
    existing = MapSet.new(models)
    missing = Enum.filter(@required_codex_models, &(not MapSet.member?(existing, &1)))

    if missing != [] do
      Logger.info("Injecting required models not returned by API: #{inspect(missing)}")
    end

    missing ++ models
  end

  defp user_agent_string do
    {os_type, os_name} = :os.type()

    os_str =
      if os_type == :unix and os_name == :darwin,
        do: "Mac OS",
        else: to_string(os_name)

    arch = to_string(:erlang.system_info(:system_architecture))

    @originator <>
      "/" <> @client_version <>
      " (" <> os_str <> "; " <> arch <> ") Terminal_Codex_CLI"
  end

  defp http_get(url, headers, params) do
    full_url = url <> "?" <> URI.encode_query(params)
    request = Finch.build(:get, full_url, headers)

    case Finch.request(request, :http_client_pool, receive_timeout: 30_000) do
      {:ok, %Finch.Response{status: 200, body: resp_body}} ->
        case Jason.decode(resp_body) do
          {:ok, decoded} -> {:ok, decoded}
          {:error, _} -> {:error, :json_decode_error}
        end

      {:ok, %Finch.Response{}} ->
        {:error, :api_unavailable}

      {:error, reason} ->
        {:error, reason}
    end
  rescue
    e -> {:error, e}
  end
end
