defmodule Mana.OAuth.TokenStore do
  @moduledoc """
  Persistent token storage for OAuth providers.

  Stores OAuth tokens as JSON files in `~/.mana/tokens/` directory.
  Provides utilities for:
  - Saving and loading tokens
  - Checking token expiration
  - Automatic refresh when needed
  - Listing and deleting stored tokens

  ## Storage Location

  Tokens are stored in `~/.mana/tokens/{provider}.json` where `{provider}`
  is a provider identifier like "chatgpt", "claude", or "antigravity".

  ## Token Format

  Tokens are expected to be maps with at least:
  - `"access_token"` - The OAuth access token
  - `"refresh_token"` (optional) - Token for refreshing access
  - `"expires_at"` (optional) - Unix timestamp when token expires
  """

  require Logger

  @default_tokens_dir "~/.mana/tokens"

  @doc """
  Get the configured tokens directory.
  """
  def tokens_dir do
    Application.get_env(:mana, :tokens_dir, @default_tokens_dir)
  end

  @doc """
  Save tokens for a provider.

  ## Examples

      :ok = Mana.OAuth.TokenStore.save("chatgpt", %{
        "access_token" => "token123",
        "expires_at" => 1234567890
      })
  """
  @spec save(String.t(), map()) :: :ok | {:error, term()}
  def save(provider, tokens) when is_binary(provider) and is_map(tokens) do
    dir = Path.expand(tokens_dir())

    case File.mkdir_p(dir) do
      :ok ->
        # Restrict directory permissions to owner-only (0700)
        File.chmod(dir, 0o700)
        path = Path.join(dir, "#{provider}.json")

        case File.write(path, Jason.encode!(tokens, pretty: true)) do
          :ok ->
            # Restrict permissions to owner-only (0600) for security
            File.chmod(path, 0o600)
            Logger.debug("Saved tokens for provider '#{provider}' to #{path}")
            :ok

          {:error, reason} ->
            Logger.error("Failed to save tokens for '#{provider}': #{inspect(reason)}")
            {:error, reason}
        end

      {:error, reason} ->
        Logger.error("Failed to create tokens directory: #{inspect(reason)}")
        {:error, reason}
    end
  end

  @doc """
  Load tokens for a provider.

  Returns `{:ok, tokens}` if found, or `{:error, :not_found}` if the
  provider has no stored tokens.

  ## Examples

      case Mana.OAuth.TokenStore.load("chatgpt") do
        {:ok, tokens} ->
          # Use tokens

        {:error, :not_found} ->
          # Need to authenticate
      end
  """
  @spec load(String.t()) :: {:ok, map()} | {:error, :not_found}
  def load(provider) when is_binary(provider) do
    path = Path.expand(Path.join(tokens_dir(), "#{provider}.json"))

    case File.read(path) do
      {:ok, data} ->
        case Jason.decode(data) do
          {:ok, tokens} ->
            Logger.debug("Loaded tokens for provider '#{provider}'")
            {:ok, tokens}

          {:error, reason} ->
            Logger.error("Failed to parse tokens for '#{provider}': #{inspect(reason)}")
            {:error, :not_found}
        end

      {:error, :enoent} ->
        {:error, :not_found}

      {:error, reason} ->
        Logger.error("Failed to read tokens for '#{provider}': #{inspect(reason)}")
        {:error, :not_found}
    end
  end

  @doc """
  Check if token is expired.

  Returns `true` if the token has an `expires_at` field and the current
  time is at or past that timestamp. Returns `false` if no expiration
  is set or if the token is still valid.

  ## Examples

      Mana.OAuth.TokenStore.expired?(%{"expires_at" => 1234567890})
      # => true or false depending on current time
  """
  @spec expired?(map()) :: boolean()
  def expired?(%{"expires_at" => expires_at}) when is_integer(expires_at) do
    System.os_time(:second) >= expires_at
  end

  def expired?(%{expires_at: expires_at}) when is_integer(expires_at) do
    System.os_time(:second) >= expires_at
  end

  def expired?(_tokens), do: false

  @doc """
  Refresh token if needed.

  Checks if the stored token for a provider is expired, and if so,
  calls the provided refresh function to get new tokens.

  The `refresh_fn` should accept the current tokens map and return
  `{:ok, new_tokens}` or `{:error, reason}`.

  ## Examples

      Mana.OAuth.TokenStore.refresh_if_needed("chatgpt", fn current_tokens ->
        # Call provider's refresh endpoint
        {:ok, %{"access_token" => "new_token", "expires_at" => 1234567890}}
      end)
  """
  @spec refresh_if_needed(String.t(), (map() -> {:ok, map()} | {:error, term()})) ::
          {:ok, map()} | {:error, term()}
  def refresh_if_needed(provider, refresh_fn) when is_function(refresh_fn, 1) do
    case load(provider) do
      {:ok, tokens} ->
        maybe_refresh(tokens, provider, refresh_fn)

      error ->
        error
    end
  end

  defp maybe_refresh(tokens, provider, refresh_fn) do
    if expired?(tokens) do
      do_refresh(tokens, provider, refresh_fn)
    else
      {:ok, tokens}
    end
  end

  defp do_refresh(tokens, provider, refresh_fn) do
    Logger.info("Token for '#{provider}' is expired, refreshing...")

    case refresh_fn.(tokens) do
      {:ok, new_tokens} ->
        save_and_return(new_tokens, provider)

      error ->
        Logger.error("Failed to refresh token for '#{provider}': #{inspect(error)}")
        error
    end
  end

  defp save_and_return(new_tokens, provider) do
    case save(provider, new_tokens) do
      :ok ->
        Logger.info("Successfully refreshed token for '#{provider}'")
        {:ok, new_tokens}

      {:error, reason} ->
        Logger.error("Failed to save refreshed tokens for '#{provider}': #{inspect(reason)}")
        # Still return the new tokens even if saving failed
        {:ok, new_tokens}
    end
  end

  @doc """
  Delete tokens for a provider.

  Removes the stored token file for the given provider. Always returns `:ok`
  even if no tokens were stored.

  ## Examples

      :ok = Mana.OAuth.TokenStore.delete("chatgpt")
  """
  @spec delete(String.t()) :: :ok
  def delete(provider) when is_binary(provider) do
    path = Path.expand(Path.join(tokens_dir(), "#{provider}.json"))

    case File.rm(path) do
      :ok ->
        Logger.info("Deleted tokens for provider '#{provider}'")
        :ok

      {:error, :enoent} ->
        :ok

      {:error, reason} ->
        Logger.warning("Failed to delete tokens for '#{provider}': #{inspect(reason)}")
        :ok
    end
  end

  @doc """
  List all stored providers.

  Returns a list of provider names that have stored tokens.

  ## Examples

      Mana.OAuth.TokenStore.list_providers()
      # => ["chatgpt", "claude"]
  """
  @spec list_providers() :: [String.t()]
  def list_providers do
    dir = Path.expand(tokens_dir())

    case File.ls(dir) do
      {:ok, files} ->
        files
        |> Enum.filter(&String.ends_with?(&1, ".json"))
        |> Enum.map(&String.replace_suffix(&1, ".json", ""))

      {:error, _} ->
        []
    end
  end

  @spec tokens_path() :: String.t()
  def tokens_path do
    Path.expand(tokens_dir())
  end
end
