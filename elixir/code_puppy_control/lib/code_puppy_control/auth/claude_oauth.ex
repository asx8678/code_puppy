defmodule CodePuppyControl.Auth.ClaudeOAuth do
  @moduledoc """
  Claude Code OAuth core configuration and token management.

  Ported from `code_puppy/plugins/claude_code_oauth/config.py` and
  `utils.py`. Provides OAuth endpoints, client config, model config,
  token persistence, and model registry management for Claude Code
  OAuth-authenticated sessions.

  All file writes go through `CodePuppyControl.Config.Isolation.safe_write!/2`
  to comply with ADR-003 dual-home isolation.

  ## Config Access

  Use `config/1` to read any config value, or call the individual
  accessor functions directly. All values are also available as module
  attributes for compile-time use.
  """

  require Logger

  alias CodePuppyControl.Config.Paths
  alias CodePuppyControl.Config.Isolation

  # ── OAuth Endpoints ─────────────────────────────────────────────────────

  @auth_url "https://claude.ai/oauth/authorize"
  @token_url "https://console.anthropic.com/v1/oauth/token"
  @api_base_url "https://api.anthropic.com"

  # ── OAuth Client Configuration ──────────────────────────────────────────

  @client_id System.get_env("CLAUDE_OAUTH_CLIENT_ID") ||
               "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
  @scope "org:create_api_key user:profile user:inference"
  @redirect_host "http://localhost"
  @redirect_path "callback"
  @callback_port_range {8765, 8795}
  @callback_timeout 180
  @console_redirect_uri "https://console.anthropic.com/oauth/code/callback"

  # ── Model Configuration ────────────────────────────────────────────────

  @prefix "claude-code-"
  @default_context_length 200_000
  @long_context_length 1_000_000
  @long_context_models ["claude-opus-4-6", "claude-opus-4-5"]
  @api_key_env_var "CLAUDE_CODE_ACCESS_TOKEN"
  @anthropic_version "2023-06-01"

  # ── Token Refresh ──────────────────────────────────────────────────────

  @token_refresh_buffer_seconds 300
  @min_refresh_buffer_seconds 30

  # ── Blocked Models ────────────────────────────────────────────────────

  @blocked_models MapSet.new([])

  # ── Model name regex patterns ─────────────────────────────────────────

  @model_modern_re ~r/^claude-(haiku|sonnet|opus)-(\d+)(?:-(\d+))?(?:-(\d+))?$/
  @model_dot_re ~r/^claude-(haiku|sonnet|opus)-(\d+)\.(\d+)(?:-(\d+))?$/
  @model_legacy_re ~r/^claude-(\d+)-(haiku|sonnet|opus)(?:-(\d+))?$/

  # ── Config Access ─────────────────────────────────────────────────────

  @doc """
  Retrieve a config value by key atom.

  Supported keys: `:auth_url`, `:token_url`, `:api_base_url`, `:client_id`,
  `:scope`, `:redirect_host`, `:redirect_path`, `:callback_port_range`,
  `:callback_timeout`, `:console_redirect_uri`, `:prefix`,
  `:default_context_length`, `:long_context_length`, `:long_context_models`,
  `:api_key_env_var`, `:anthropic_version`.
  """
  @spec config(atom()) :: term()
  def config(:auth_url), do: @auth_url
  def config(:token_url), do: @token_url
  def config(:api_base_url), do: @api_base_url
  def config(:client_id), do: @client_id
  def config(:scope), do: @scope
  def config(:redirect_host), do: @redirect_host
  def config(:redirect_path), do: @redirect_path
  def config(:callback_port_range), do: @callback_port_range
  def config(:callback_timeout), do: @callback_timeout
  def config(:console_redirect_uri), do: @console_redirect_uri
  def config(:prefix), do: @prefix
  def config(:default_context_length), do: @default_context_length
  def config(:long_context_length), do: @long_context_length
  def config(:long_context_models), do: @long_context_models
  def config(:api_key_env_var), do: @api_key_env_var
  def config(:anthropic_version), do: @anthropic_version
  def config(_), do: nil

  # Convenience accessors for the most commonly used values
  @spec auth_url() :: String.t()
  def auth_url, do: @auth_url
  @spec token_url() :: String.t()
  def token_url, do: @token_url
  @spec api_base_url() :: String.t()
  def api_base_url, do: @api_base_url
  @spec client_id() :: String.t()
  def client_id, do: @client_id
  @spec prefix() :: String.t()
  def prefix, do: @prefix
  @spec anthropic_version() :: String.t()
  def anthropic_version, do: @anthropic_version

  # ── Public API: Path Resolution ────────────────────────────────────────

  @doc """
  Path to the OAuth token storage file.

  Located in the data directory: `{data_dir}/claude_code_oauth.json`.
  Ensures the data directory exists before returning the path.
  """
  @spec token_storage_path() :: String.t()
  def token_storage_path do
    dir = Paths.data_dir()
    Isolation.safe_mkdir_p!(dir)
    Path.join(dir, "claude_code_oauth.json")
  end

  @doc """
  Path to the Claude models overlay JSON file.

  Delegates to `CodePuppyControl.Config.Paths.claude_models_file/0`.
  """
  @spec claude_models_path() :: String.t()
  def claude_models_path, do: Paths.claude_models_file()

  # ── Public API: Token Persistence ─────────────────────────────────────

  @doc """
  Load stored OAuth tokens from disk.

  Returns `{:ok, map}` if tokens exist and parse as JSON,
  `{:error, :not_found}` if the file doesn't exist, or
  `{:error, reason}` on any other failure.
  """
  @spec load_tokens() :: {:ok, map()} | {:error, :not_found | term()}
  def load_tokens do
    path = token_storage_path()

    case File.read(path) do
      {:ok, data} ->
        case Jason.decode(data) do
          {:ok, tokens} when is_map(tokens) ->
            {:ok, tokens}

          {:error, reason} ->
            Logger.error("Failed to parse OAuth tokens: #{inspect(reason)}")
            {:error, reason}
        end

      {:error, :enoent} ->
        {:error, :not_found}

      {:error, reason} ->
        Logger.error("Failed to load OAuth tokens: #{inspect(reason)}")
        {:error, reason}
    end
  end

  @doc """
  Save OAuth tokens to disk with restricted permissions.

  Uses `Isolation.safe_write!/2` for ADR-003 compliance.
  Returns `:ok` on success, raises on failure.
  """
  @spec save_tokens(map()) :: :ok
  def save_tokens(tokens) when is_map(tokens) do
    path = token_storage_path()
    json = Jason.encode!(tokens, pretty: true)
    Isolation.safe_write!(path, json)
    File.chmod(path, 0o600)
    :ok
  end

  # ── Public API: Token Expiry ───────────────────────────────────────────

  @doc "Check if tokens are expired (with proactive refresh buffer)."
  @spec token_expired?(map()) :: boolean()
  def token_expired?(tokens) when is_map(tokens) do
    case get_expires_at(tokens) do
      nil ->
        false

      expires_at ->
        buffer = calculate_refresh_buffer(tokens["expires_in"])
        System.system_time(:second) >= expires_at - buffer
    end
  end

  @doc "Check if tokens are actually expired (no buffer)."
  @spec token_actually_expired?(map()) :: boolean()
  def token_actually_expired?(tokens) when is_map(tokens) do
    case get_expires_at(tokens) do
      nil -> false
      expires_at -> System.system_time(:second) >= expires_at
    end
  end

  # ── Public API: Model Fetching ─────────────────────────────────────────

  @doc """
  Fetch available Claude models from the Anthropic API.

  Returns `{:ok, [model_name]}` on success or `{:error, reason}` on failure.
  Response bodies are never logged — they may contain sensitive data.
  """
  @spec fetch_models(String.t()) :: {:ok, [String.t()]} | {:error, term()}
  def fetch_models(access_token) when is_binary(access_token) do
    url = "#{@api_base_url}/v1/models"

    headers = [
      {"Authorization", "Bearer #{access_token}"},
      {"Content-Type", "application/json"},
      {"anthropic-beta", "oauth-2025-04-20"},
      {"anthropic-version", @anthropic_version}
    ]

    case :httpc.request(:get, {to_charlist(url), headers}, httpc_opts(), []) do
      {:ok, {{_version, 200, _reason}, _resp_headers, body}} ->
        parse_models_response(body)

      {:ok, {{_version, status, _reason}, _resp_headers, _body}} ->
        Logger.error("Failed to fetch models: status=#{status}")
        {:error, {:http_error, status}}

      {:error, reason} ->
        Logger.error("Error fetching Claude models: #{inspect(reason)}")
        {:error, reason}
    end
  end

  # ── Public API: Model Filtering ────────────────────────────────────────

  @doc """
  Filter model names to keep only the latest per family (haiku, sonnet, opus).

  `max_per_family` can be an integer (applies to all) or a map with
  family keys (missing keys fall back to `"default"`, then `2`).
  """
  @spec filter_latest_models([String.t()], max_per_family()) :: [String.t()]
  def filter_latest_models(models, max_per_family \\ 2)
  def filter_latest_models([], _), do: []

  def filter_latest_models(models, max_per_family) when is_list(models) do
    models
    |> Enum.reduce(%{}, fn name, acc ->
      case parse_model_name(name) do
        nil ->
          acc

        {family, major, minor, date} ->
          Map.update(acc, family, [{name, major, minor, date}], fn existing ->
            [{name, major, minor, date} | existing]
          end)
      end
    end)
    |> Enum.flat_map(fn {family, entries} ->
      limit = resolve_limit(family, max_per_family)

      entries
      |> Enum.sort_by(fn {_, major, minor, date} -> {major, minor, date} end, :desc)
      |> Enum.take(limit)
      |> Enum.map(fn {name, _, _, _} -> name end)
    end)
  end

  # ── Public API: Model Registry ─────────────────────────────────────────

  @doc "Load Claude models from the overlay JSON file, filtering blocked ones."
  @spec load_models() :: {:ok, map()}
  def load_models do
    path = claude_models_path()

    case File.read(path) do
      {:ok, data} ->
        case Jason.decode(data) do
          {:ok, models} when is_map(models) ->
            {:ok, filter_blocked_models(models)}

          {:error, reason} ->
            Logger.error("Failed to parse Claude models: #{inspect(reason)}")
            {:ok, %{}}
        end

      {:error, :enoent} ->
        {:ok, %{}}

      {:error, reason} ->
        Logger.error("Failed to load Claude models: #{inspect(reason)}")
        {:ok, %{}}
    end
  end

  @doc "Save Claude models to the overlay JSON file (0o600 permissions)."
  @spec save_models(map()) :: :ok
  def save_models(models) when is_map(models) do
    path = claude_models_path()
    json = Jason.encode!(models, pretty: true)
    Isolation.safe_write!(path, json)
    File.chmod(path, 0o600)
    :ok
  end

  @doc """
  Add model names to the registry, overwriting existing entries.

  Creates `-long` variants for models in `long_context_models/0`.
  Returns `{:ok, count}` or `{:error, reason}`.
  """
  @spec add_models([String.t()]) :: {:ok, non_neg_integer()} | {:error, term()}
  def add_models(model_names) when is_list(model_names) do
    filtered = Enum.reject(model_names, &blocked_model?/1)
    access_token = current_access_token()

    {models, added} =
      Enum.reduce(filtered, {%{}, 0}, fn name, {acc, count} ->
        prefixed = "#{@prefix}#{name}"
        entry = build_model_entry(name, @default_context_length, access_token)
        new_acc = Map.put(acc, prefixed, entry)

        if name in @long_context_models do
          long_prefixed = "#{@prefix}#{name}-long"
          long_entry = build_model_entry(name, @long_context_length, access_token)
          {Map.put(new_acc, long_prefixed, long_entry), count + 2}
        else
          {new_acc, count + 1}
        end
      end)

    try do
      save_models(models)
      Logger.info("Added #{added} Claude Code models")
      {:ok, added}
    rescue
      e ->
        Logger.error("Error adding models: #{inspect(e)}")
        {:error, e}
    end
  end

  @doc """
  Load Claude models, filtered to only the latest per family.

  Returns only the most recent haiku, sonnet, and opus models
  (default: 1 per family, opus up to 6). Useful for status display
  where showing every dated snapshot is noise.

  Renamed from `load_models_filtered` to clarify that filtering
  is specifically by latest-per-family, not a generic filter.
  """
  @spec load_latest_models() :: {:ok, map()}
  def load_latest_models do
    {:ok, all_models} = load_models()

    if map_size(all_models) == 0 do
      {:ok, %{}}
    else
      # Extract model names from OAuth-sourced entries
      model_names =
        all_models
        |> Enum.filter(fn {_, cfg} -> cfg["oauth_source"] == "claude-code-plugin" end)
        |> Enum.map(fn {_, cfg} -> cfg["name"] || "" end)
        |> Enum.filter(&(&1 != ""))

      latest_names =
        filter_latest_models(model_names, %{"default" => 1, "opus" => 6})
        |> MapSet.new()

      filtered =
        all_models
        |> Enum.filter(fn {_, cfg} ->
          name = cfg["name"] || ""
          MapSet.member?(latest_names, name)
        end)
        |> Map.new()

      Logger.info(
        "Loaded #{map_size(all_models)} models, filtered to #{map_size(filtered)} latest models"
      )

      {:ok, filtered}
    end
  end

  @doc "Remove all Claude Code OAuth models. Returns `{:ok, count}` or `{:error, reason}`."
  @spec remove_models() :: {:ok, non_neg_integer()} | {:error, term()}
  def remove_models do
    case load_models() do
      {:ok, all_models} ->
        to_remove =
          all_models
          |> Enum.filter(fn {_, cfg} -> cfg["oauth_source"] == "claude-code-plugin" end)
          |> Enum.map(fn {name, _} -> name end)

        if to_remove == [] do
          {:ok, 0}
        else
          try do
            save_models(Map.drop(all_models, to_remove))
            Logger.info("Removed #{length(to_remove)} Claude Code models")
            {:ok, length(to_remove)}
          rescue
            e ->
              Logger.error("Error removing models: #{inspect(e)}")
              {:error, e}
          end
        end
    end
  end

  # ── Private: Model Parsing ─────────────────────────────────────────────

  @spec parse_model_name(String.t()) :: {String.t(), integer(), integer(), integer()} | nil
  defp parse_model_name(name) do
    cond do
      match = Regex.run(@model_modern_re, name) ->
        [_, family, major_s, g3, g4] = pad_match(match, 5)
        {major, minor, date} = parse_modern_groups(major_s, g3, g4)
        {family, major, minor, date}

      match = Regex.run(@model_dot_re, name) ->
        [_, family, major_s, minor_s, date_s] = pad_match(match, 5)
        major = String.to_integer(major_s)
        minor = String.to_integer(minor_s)
        date = if date_s == "", do: 99_999_999, else: String.to_integer(date_s)
        {family, major, minor, date}

      match = Regex.run(@model_legacy_re, name) ->
        [_, major_s, family, date_s] = pad_match(match, 4)
        major = String.to_integer(major_s)
        date = if date_s == "", do: 99_999_999, else: String.to_integer(date_s)
        {family, major, 0, date}

      true ->
        nil
    end
  end

  defp pad_match(match, desired_len) do
    match ++ List.duplicate("", desired_len - length(match))
  end

  defp parse_modern_groups(major_s, g3, g4) do
    major = String.to_integer(major_s)

    cond do
      g3 == "" -> {major, 0, 99_999_999}
      g4 != "" -> {major, String.to_integer(g3), String.to_integer(g4)}
      String.length(g3) >= 6 -> {major, 0, String.to_integer(g3)}
      true -> {major, String.to_integer(g3), 99_999_999}
    end
  end

  # ── Private: Blocked Models ────────────────────────────────────────────

  defp blocked_model?(name) when is_binary(name) do
    stripped = name |> String.trim_leading(@prefix) |> String.trim_trailing("-long")
    MapSet.member?(@blocked_models, name) or MapSet.member?(@blocked_models, stripped)
  end

  defp blocked_model?(_), do: false

  defp filter_blocked_models(models) do
    {kept, dropped} =
      Enum.reduce(models, {%{}, []}, fn {key, val}, {kept_acc, drop_acc} ->
        if blocked_model?(key),
          do: {kept_acc, [key | drop_acc]},
          else: {Map.put(kept_acc, key, val), drop_acc}
      end)

    if dropped != [] do
      Logger.info("Filtered blocked Claude Code models: #{inspect(Enum.reverse(dropped))}")
    end

    kept
  end

  # ── Private: Token Helpers ─────────────────────────────────────────────

  defp get_expires_at(%{"expires_at" => val}) when is_number(val), do: trunc(val)
  defp get_expires_at(_), do: nil

  defp calculate_refresh_buffer(nil), do: @token_refresh_buffer_seconds

  defp calculate_refresh_buffer(expires_in) when is_number(expires_in) do
    min(
      @token_refresh_buffer_seconds,
      max(@min_refresh_buffer_seconds, trunc(expires_in * 0.1))
    )
  end

  defp calculate_refresh_buffer(_), do: @token_refresh_buffer_seconds

  # ── Private: Model Entry Builder ──────────────────────────────────────

  defp current_access_token do
    case load_tokens() do
      {:ok, %{"access_token" => access_token}} when is_binary(access_token) -> access_token
      _ -> ""
    end
  end

  defp build_model_entry(model_name, context_length, access_token) do
    settings =
      base_supported_settings() ++
        if String.contains?(String.downcase(model_name), "opus"), do: ["effort"], else: []

    %{
      "type" => "claude_code",
      "name" => model_name,
      "custom_endpoint" => %{
        "url" => @api_base_url,
        "api_key" => access_token,
        "headers" => %{
          "anthropic-beta" => "oauth-2025-04-20,interleaved-thinking-2025-05-14",
          "x-app" => "cli",
          "User-Agent" => "claude-cli/2.0.61 (external, cli)"
        }
      },
      "context_length" => context_length,
      "oauth_source" => "claude-code-plugin",
      "supported_settings" => settings
    }
  end

  defp base_supported_settings do
    ["temperature", "extended_thinking", "budget_tokens", "interleaved_thinking"]
  end

  # ── Private: HTTP ─────────────────────────────────────────────────────

  defp httpc_opts do
    [
      timeout: 30_000,
      connect_timeout: 10_000,
      ssl: [verify: :verify_peer, cacerts: :public_key.cacerts_get()]
    ]
  end

  defp parse_models_response(body) do
    case Jason.decode(body) do
      {:ok, %{"data" => models}} when is_list(models) ->
        names =
          models
          |> Enum.map(fn m -> m["id"] || m["name"] end)
          |> Enum.filter(&is_binary/1)

        {:ok, names}

      {:ok, _} ->
        Logger.error("Unexpected models response shape")
        {:error, :unexpected_response}

      {:error, reason} ->
        Logger.error("Failed to parse models response: #{inspect(reason)}")
        {:error, reason}
    end
  end

  # ── Private: Max Per Family ────────────────────────────────────────────

  @type max_per_family :: pos_integer() | %{String.t() => pos_integer()}

  defp resolve_limit(_, max) when is_integer(max), do: max

  defp resolve_limit(family, max) when is_map(max) do
    Map.get(max, family, Map.get(max, "default", 2))
  end

  # ── Public API: Token Refresh & Model Token Updates ───────────────────

  @doc """
  Run the interactive Claude Code OAuth browser flow.
  """
  @spec run_oauth_flow() :: :ok | {:error, term()}
  def run_oauth_flow do
    CodePuppyControl.Auth.ClaudeOAuth.Flow.run_oauth_flow()
  end

  @doc """
  Get a valid access token, refreshing if needed.
  """
  @spec get_valid_access_token() :: {:ok, String.t()} | {:error, term()}
  def get_valid_access_token do
    CodePuppyControl.Auth.ClaudeOAuth.Flow.get_valid_access_token()
  end

  @doc """
  Refresh the access token using the stored refresh token.
  """
  @spec refresh_access_token() :: {:ok, String.t()} | {:error, term()}
  def refresh_access_token do
    CodePuppyControl.Auth.ClaudeOAuth.Flow.refresh_access_token()
  end

  @doc """
  Update the access token in all saved Claude Code model entries.

  This preserves the Python plugin semantic where the live OAuth access token
  is stored in `custom_endpoint.api_key` for `oauth_source == "claude-code-plugin"`.
  """
  @spec update_model_tokens(String.t()) :: :ok | {:error, term()}
  def update_model_tokens(access_token) when is_binary(access_token) do
    {:ok, models} = load_models()

    updated =
      models
      |> Enum.map(fn {name, config} ->
        if config["oauth_source"] == "claude-code-plugin" do
          custom_endpoint = Map.get(config, "custom_endpoint", %{})
          updated_endpoint = Map.put(custom_endpoint, "api_key", access_token)
          {name, Map.put(config, "custom_endpoint", updated_endpoint)}
        else
          {name, config}
        end
      end)
      |> Map.new()

    try do
      save_models(updated)
      :ok
    rescue
      e -> {:error, e}
    end
  end
end
