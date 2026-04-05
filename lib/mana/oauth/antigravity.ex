defmodule Mana.OAuth.Antigravity do
  @moduledoc """
  Google Antigravity proxy OAuth provider for Gemini/Claude models.

  This module implements the Mana.Models.Provider behaviour for the Google
  Antigravity API, which provides access to Gemini and Claude models via
  Google OAuth authentication.

  Features:
  - PKCE OAuth flow for secure authentication
  - Multi-account support with automatic rotation
  - Rate-limit aware account selection
  - Model catalog for available Gemini and Claude models

  ## Configuration

  The provider uses a built-in Google OAuth client configuration and stores
  tokens in the standard Mana token store location.

  ## Usage

      # Start the provider (optional, auto-started on first use)
      Mana.OAuth.Antigravity.start_link()

      # List available models
      models = Mana.OAuth.Antigravity.list_models()

      # Start OAuth flow
      {:ok, tokens} = Mana.OAuth.Antigravity.start_oauth()

      # Use with the provider system
      config = %{provider: "antigravity", model: "gemini-3-pro"}
  """

  use GenServer

  @behaviour Mana.Models.Provider

  alias Mana.OAuth.Antigravity.Transport
  alias Mana.OAuth.{Flow, RefreshManager, TokenStore}

  require Logger

  # Google OAuth configuration
  @client_id "681255704224-90e21v2jqj9r1jq8qk4j8k4j8k4j8k4j.apps.googleusercontent.com"
  @auth_url "https://accounts.google.com/o/oauth2/v2/auth"
  @token_url "https://oauth2.googleapis.com/token"
  @api_base "https://antigravity.googleapis.com/v1"

  # OAuth scopes required for Antigravity
  @scopes [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile"
  ]

  @doc """
  Model catalog for available Antigravity models.

  Contains specifications for Gemini and Claude models including
  context window size and feature support.
  """
  @models %{
    "gemini-3-pro" => %{
      context: 1_000_000,
      supports_tools: true,
      supports_vision: true,
      provider: "google"
    },
    "gemini-3-pro-low" => %{
      context: 500_000,
      supports_tools: true,
      supports_vision: true,
      provider: "google"
    },
    "gemini-3-pro-high" => %{
      context: 1_000_000,
      supports_tools: true,
      supports_vision: true,
      provider: "google"
    },
    "gemini-3-flash" => %{
      context: 1_000_000,
      supports_tools: true,
      supports_vision: true,
      provider: "google"
    },
    "claude-opus-4-6" => %{
      context: 200_000,
      supports_tools: true,
      supports_vision: true,
      thinking: true,
      provider: "anthropic"
    },
    "claude-opus-4-6-thinking" => %{
      context: 200_000,
      supports_tools: true,
      supports_vision: true,
      thinking: true,
      provider: "anthropic"
    }
  }

  # Multi-account pool state
  defstruct accounts: [],
            current_index: 0,
            rate_limits: %{},
            last_used: %{}

  # ============================================================================
  # GenServer API
  # ============================================================================

  @doc """
  Start the Antigravity provider GenServer.

  ## Options

  - `:name` - The name to register the process under (default: `__MODULE__`)

  ## Examples

      {:ok, pid} = Mana.OAuth.Antigravity.start_link()
      {:ok, pid} = Mana.OAuth.Antigravity.start_link(name: :my_antigravity)
  """
  @spec start_link(keyword()) :: GenServer.on_start()
  def start_link(opts \\ []) do
    name = Keyword.get(opts, :name, __MODULE__)
    GenServer.start_link(__MODULE__, opts, name: name)
  end

  @doc """
  Initialize the GenServer state.
  """
  @impl true
  def init(_opts) do
    # Load existing accounts from token store
    accounts = load_accounts_from_store()

    state = %__MODULE__{
      accounts: accounts,
      current_index: 0,
      rate_limits: %{},
      last_used: %{}
    }

    {:ok, state}
  end

  # ============================================================================
  # Model Catalog API
  # ============================================================================

  @doc """
  List all available Antigravity models.

  Returns a map of model names to their specifications.

  ## Examples

      models = Mana.OAuth.Antigravity.list_models()
      # => %{
      #   "gemini-3-pro" => %{context: 1_000_000, supports_tools: true, ...},
      #   ...
      # }
  """
  @spec list_models() :: %{String.t() => map()}
  def list_models, do: @models

  @doc """
  Get specifications for a specific model.

  Returns `{:ok, specs}` if the model exists, or `{:error, :not_found}`
  if the model is not in the catalog.

  ## Examples

      {:ok, specs} = Mana.OAuth.Antigravity.get_model("gemini-3-pro")
      {:error, :not_found} = Mana.OAuth.Antigravity.get_model("unknown-model")
  """
  @spec get_model(String.t()) :: {:ok, map()} | {:error, :not_found}
  def get_model(name) when is_binary(name) do
    case Map.get(@models, name) do
      nil -> {:error, :not_found}
      specs -> {:ok, specs}
    end
  end

  # ============================================================================
  # OAuth Flow API
  # ============================================================================

  @doc """
  Start the OAuth flow for a new Antigravity account.

  This initiates the PKCE OAuth flow with Google, opens a browser for
  user authorization, and stores the resulting tokens.

  ## Options

  - `:account_id` - Custom account identifier (default: auto-generated)
  - `:port` - Port for callback server (default: 1455)
  - `:timeout` - OAuth flow timeout in milliseconds (default: 300000)

  ## Examples

      {:ok, tokens} = Mana.OAuth.Antigravity.start_oauth()
      {:ok, tokens} = Mana.OAuth.Antigravity.start_oauth(account_id: "work-account")
  """
  @spec start_oauth(keyword()) :: {:ok, map()} | {:error, term()}
  def start_oauth(opts \\ []) do
    account_id = Keyword.get(opts, :account_id, generate_account_id())
    port = Keyword.get(opts, :port, 1455)
    timeout = Keyword.get(opts, :timeout, 300_000)

    # Build authorization URL with required scopes
    auth_url = build_auth_url(port)

    # Run the OAuth flow
    case Flow.run_flow(auth_url, @token_url,
           client_id: @client_id,
           port: port,
           timeout: timeout
         ) do
      {:ok, tokens} ->
        # Store tokens with account identifier
        provider_key = "antigravity_#{account_id}"

        tokens_with_metadata =
          Map.merge(tokens, %{
            "account_id" => account_id,
            "provider" => "antigravity",
            "created_at" => System.os_time(:second)
          })

        case TokenStore.save(provider_key, tokens_with_metadata) do
          :ok ->
            # Register the account with the GenServer
            GenServer.call(__MODULE__, {:register_account, account_id})
            Logger.info("Successfully authenticated Antigravity account: #{account_id}")
            {:ok, tokens_with_metadata}

          {:error, reason} ->
            {:error, "Failed to save tokens: #{inspect(reason)}"}
        end

      {:error, reason} ->
        {:error, reason}
    end
  end

  @doc """
  Handle an OAuth callback directly (for external OAuth flows).

  This is useful when the OAuth flow is handled by an external system
  and only the callback parameters need to be processed.

  ## Examples

      {:ok, tokens} = Mana.OAuth.Antigravity.handle_callback(%{"code" => "abc123"})
  """
  @spec handle_callback(map()) :: {:ok, map()} | {:error, term()}
  def handle_callback(params) do
    code = params["code"] || params[:code]

    if is_nil(code) do
      {:error, "Missing authorization code in callback"}
    else
      # Exchange code for tokens
      # Note: This requires the code_verifier from the original PKCE request
      # In practice, this should be stored during the initial auth URL generation
      {:error, "Direct callback handling requires PKCE state management"}
    end
  end

  @doc """
  Get the access token for a specific account.

  Returns `{:ok, token}` if a valid token exists, or `{:error, reason}`
  if the token is missing or expired. Uses RefreshManager to serialize
  refresh attempts and prevent race conditions.

  ## Examples

      {:ok, token} = Mana.OAuth.Antigravity.get_token("my-account")
      {:error, :not_found} = Mana.OAuth.Antigravity.get_token("unknown-account")
  """
  @spec get_token(String.t()) :: {:ok, String.t()} | {:error, term()}
  def get_token(account_id) when is_binary(account_id) do
    provider_key = "antigravity_#{account_id}"

    case TokenStore.load(provider_key) do
      {:ok, tokens} ->
        get_token_from_loaded(provider_key, tokens, account_id)

      {:error, :not_found} ->
        {:error, :not_found}
    end
  end

  # Extracted helper to reduce cyclomatic complexity in get_token/1
  defp get_token_from_loaded(provider_key, tokens, account_id) do
    if TokenStore.expired?(tokens) do
      handle_expired_token(provider_key, tokens, account_id)
    else
      {:ok, tokens["access_token"]}
    end
  end

  # Extracted helper to handle expired token refresh logic
  defp handle_expired_token(provider_key, tokens, account_id) do
    case tokens["refresh_token"] || tokens[:refresh_token] do
      nil ->
        {:error, :expired}

      refresh_token when is_binary(refresh_token) ->
        execute_token_refresh(provider_key, refresh_token, account_id)
    end
  end

  # Extracted helper to execute token refresh and extract access token
  defp execute_token_refresh(provider_key, refresh_token, account_id) do
    RefreshManager.execute_refresh(provider_key, fn _ ->
      do_refresh_and_save(provider_key, refresh_token, account_id)
    end)
    |> case do
      {:ok, new_tokens} -> {:ok, new_tokens["access_token"]}
      error -> error
    end
  end

  # Extracted helper to perform refresh call and save tokens
  defp do_refresh_and_save(provider_key, refresh_token, account_id) do
    case do_refresh_token_call(refresh_token, account_id) do
      {:ok, new_tokens} ->
        case save_refreshed_tokens(provider_key, new_tokens) do
          :ok -> {:ok, new_tokens}
          error -> error
        end

      error ->
        error
    end
  end

  @doc """
  Refresh the token for a specific account.

  Uses the stored refresh_token to obtain a new access_token.
  Uses RefreshManager to serialize refresh attempts and prevent
  race conditions when multiple requests trigger refresh simultaneously.

  ## Examples

      {:ok, new_tokens} = Mana.OAuth.Antigravity.refresh_token("my-account")
  """
  @spec refresh_token(String.t()) :: {:ok, map()} | {:error, term()}
  def refresh_token(account_id) when is_binary(account_id) do
    provider_key = "antigravity_#{account_id}"

    with {:ok, tokens} <- TokenStore.load(provider_key),
         refresh_token when is_binary(refresh_token) <-
           tokens["refresh_token"] || tokens[:refresh_token] do
      RefreshManager.execute_refresh(provider_key, fn _ ->
        do_refresh_and_save(provider_key, refresh_token, account_id)
      end)
    else
      nil -> {:error, "No refresh token available"}
      {:error, reason} -> {:error, reason}
      error -> error
    end
  end

  defp do_refresh_token_call(refresh_token, account_id) do
    body = %{
      grant_type: "refresh_token",
      refresh_token: refresh_token,
      client_id: @client_id
    }

    case Req.post(@token_url, json: body) do
      {:ok, %{status: 200, body: new_tokens}} ->
        merged_tokens =
          Map.merge(new_tokens, %{
            "account_id" => account_id,
            "provider" => "antigravity",
            "refreshed_at" => System.os_time(:second)
          })

        {:ok, merged_tokens}

      {:ok, %{status: status, body: body}} ->
        {:error, "Token refresh failed: HTTP #{status} - #{inspect(body)}"}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp save_refreshed_tokens(provider_key, tokens) do
    case TokenStore.save(provider_key, tokens) do
      :ok -> :ok
      {:error, reason} -> {:error, reason}
    end
  end

  # ============================================================================
  # Provider Behaviour Callbacks
  # ============================================================================

  @doc """
  Returns the unique provider identifier.
  """
  @impl Mana.Models.Provider
  def provider_id, do: "antigravity"

  @doc """
  Validates the provider configuration.

  Checks that a valid Antigravity token is available.
  """
  @impl Mana.Models.Provider
  def validate_config(config) when is_map(config) do
    account_id = config[:account_id] || default_account()

    if is_nil(account_id) do
      {:error, "No Antigravity account configured"}
    else
      case get_token(account_id) do
        {:ok, _token} -> :ok
        {:error, :not_found} -> {:error, "No valid Antigravity token for account: #{account_id}"}
        {:error, :expired} -> {:error, "Antigravity token expired for account: #{account_id}"}
        {:error, reason} -> {:error, "Antigravity token validation failed: #{inspect(reason)}"}
      end
    end
  end

  @doc """
  Performs a completion request via the Antigravity API.

  ## Options

  - `:temperature` - Sampling temperature (0.0 to 1.0)
  - `:max_tokens` - Maximum tokens to generate
  - `:tools` - List of tool definitions for function calling

  ## Examples

      {:ok, response} = Mana.OAuth.Antigravity.complete(
        [%{role: "user", content: "Hello"}],
        "gemini-3-pro",
        temperature: 0.7
      )
  """
  @impl Mana.Models.Provider
  def complete(messages, model, opts \\ []) do
    # Validate model exists
    case get_model(model) do
      {:ok, _specs} -> :ok
      {:error, :not_found} -> Logger.warning("Unknown Antigravity model: #{model}")
    end

    # Select account for this request
    account = select_account()

    # Build request body
    body = %{
      "model" => model,
      "messages" => convert_messages(messages),
      "stream" => false
    }

    # Add optional parameters
    body = maybe_add_temperature(body, opts)
    body = maybe_add_max_tokens(body, opts)
    body = maybe_add_tools(body, opts)

    # Make the API request
    case Transport.request(:post, "#{@api_base}/chat/completions", body, account: account) do
      {:ok, response} ->
        {:ok, parse_response(response, model)}

      {:error, %{status: 429} = _reason} ->
        # Rate limited - mark account and retry with another
        mark_rate_limited(account)
        complete(messages, model, opts)

      {:error, reason} ->
        handle_error(reason, account)
    end
  end

  @doc """
  Performs a streaming completion request via the Antigravity API.

  Returns an `Enumerable.t()` that yields stream events.

  ## Events

  - `{:part_start, index, type, metadata}` - Start of a content part
  - `{:part_delta, index, content}` - Content delta/chunk
  - `{:part_end, index, metadata}` - End of a content part

  ## Examples

      stream = Mana.OAuth.Antigravity.stream(
        [%{role: "user", content: "Hello"}],
        "gemini-3-pro"
      )

      Enum.each(stream, fn event ->
        IO.inspect(event)
      end)
  """
  @impl Mana.Models.Provider
  def stream(messages, model, opts \\ []) do
    account = select_account()

    # Build request body for streaming
    body = %{
      "model" => model,
      "messages" => convert_messages(messages),
      "stream" => true
    }

    # Add optional parameters
    body = maybe_add_temperature(body, opts)
    body = maybe_add_max_tokens(body, opts)
    body = maybe_add_tools(body, opts)

    # Get the stream from transport
    Transport.stream("#{@api_base}/chat/completions", body, account: account)
  end

  # ============================================================================
  # GenServer Callbacks
  # ============================================================================

  @impl true
  def handle_call({:register_account, account_id}, _from, state) do
    if account_id in state.accounts do
      {:reply, :ok, state}
    else
      new_state = %{state | accounts: state.accounts ++ [account_id]}
      {:reply, :ok, new_state}
    end
  end

  @impl true
  def handle_call(:select_account, _from, state) do
    {account, new_state} = do_select_account(state)
    {:reply, account, new_state}
  end

  @impl true
  def handle_call({:mark_rate_limited, account_id}, _from, state) do
    now = System.os_time(:second)
    # Mark as rate limited for 60 seconds
    new_limits = Map.put(state.rate_limits, account_id, now + 60)
    new_state = %{state | rate_limits: new_limits}
    {:reply, :ok, new_state}
  end

  @impl true
  def handle_call(:list_accounts, _from, state) do
    {:reply, state.accounts, state}
  end

  @impl true
  def handle_call(:get_state, _from, state) do
    {:reply, state, state}
  end

  # ============================================================================
  # Private Functions
  # ============================================================================

  defp build_auth_url(port) do
    redirect_uri = "http://localhost:#{port}/callback"

    params = %{
      client_id: @client_id,
      redirect_uri: redirect_uri,
      response_type: "code",
      scope: Enum.join(@scopes, " "),
      access_type: "offline",
      prompt: "consent"
    }

    @auth_url <> "?" <> URI.encode_query(params)
  end

  defp generate_account_id do
    timestamp = System.os_time(:second)
    random = :crypto.strong_rand_bytes(4) |> Base.url_encode64(padding: false)
    "account_#{timestamp}_#{random}"
  end

  defp load_accounts_from_store do
    TokenStore.list_providers()
    |> Enum.filter(&String.starts_with?(&1, "antigravity_"))
    |> Enum.map(&String.replace_prefix(&1, "antigravity_", ""))
  end

  defp default_account do
    case load_accounts_from_store() do
      [] -> nil
      [first | _] -> first
    end
  end

  # Multi-account selection with rate-limit awareness
  defp select_account do
    GenServer.call(__MODULE__, :select_account)
  end

  defp do_select_account(state) do
    now = System.os_time(:second)

    # Filter out rate-limited accounts
    available_accounts =
      Enum.filter(state.accounts, fn account ->
        case Map.get(state.rate_limits, account) do
          nil -> true
          expiry -> now > expiry
        end
      end)

    accounts_to_use = if available_accounts == [], do: state.accounts, else: available_accounts

    if accounts_to_use == [] do
      # No accounts configured
      {nil, state}
    else
      # Round-robin selection
      index = rem(state.current_index, length(accounts_to_use))
      account = Enum.at(accounts_to_use, index)
      new_state = %{state | current_index: state.current_index + 1}
      {account, new_state}
    end
  end

  defp mark_rate_limited(account_id) do
    GenServer.call(__MODULE__, {:mark_rate_limited, account_id})
  end

  # Message conversion for Antigravity API format
  defp convert_messages(messages) when is_list(messages) do
    Enum.map(messages, &convert_message/1)
  end

  defp convert_message(%{role: role, content: content}) do
    %{
      "role" => role,
      "content" => content
    }
  end

  defp convert_message(%{"role" => role, "content" => content}) do
    %{
      "role" => role,
      "content" => content
    }
  end

  defp convert_message(other), do: other

  # Response parsing
  defp parse_response(response, model) when is_map(response) do
    %{
      content: extract_content(response),
      usage: response["usage"] || %{},
      model: model,
      tool_calls: response["tool_calls"] || []
    }
  end

  defp extract_content(%{"choices" => [choice | _]}) do
    message = choice["message"] || %{}
    message["content"] || ""
  end

  defp extract_content(%{"content" => content}) when is_binary(content) do
    content
  end

  defp extract_content(_), do: ""

  # Error handling
  defp handle_error(%{status: status, body: body}, account) do
    Logger.error("Antigravity API error (account: #{account}): HTTP #{status} - #{inspect(body)}")
    {:error, "Antigravity API error: HTTP #{status}"}
  end

  defp handle_error(reason, account) do
    Logger.error("Antigravity request failed (account: #{account}): #{inspect(reason)}")
    {:error, "Request failed: #{inspect(reason)}"}
  end

  # Optional parameter handling
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
end
