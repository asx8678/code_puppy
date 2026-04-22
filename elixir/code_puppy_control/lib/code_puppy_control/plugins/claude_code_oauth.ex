defmodule CodePuppyControl.Plugins.ClaudeCodeOAuth do
  @moduledoc """
  Claude Code OAuth plugin.

  Provides browser-based OAuth authentication for Claude Code models,
  token refresh, and model discovery.

  Ported from Python: code_puppy/plugins/claude_code_oauth/
  """

  use CodePuppyControl.Plugins.PluginBehaviour

  alias CodePuppyControl.Callbacks
  alias CodePuppyControl.Auth.ClaudeOAuth
  alias CodePuppyControl.Config.Isolation

  @impl true
  def name, do: "claude_code_oauth"

  @impl true
  def description, do: "Claude Code OAuth authentication and model management"

  @impl true
  def register do
    Callbacks.register(:startup, &__MODULE__._on_startup/0)
    Callbacks.register(:custom_command, &__MODULE__._handle_custom_command/2)
    Callbacks.register(:custom_command_help, &__MODULE__._custom_help/0)
    Callbacks.register(:register_model_type, &__MODULE__._register_model_types/0)
    :ok
  end

  # ── Callback Implementations ─────────────────────────────────────

  @doc false
  def _on_startup do
    # Proactively refresh tokens at startup if they exist
    case ClaudeOAuth.load_tokens() do
      {:ok, tokens} ->
        if tokens["access_token"] do
          case ClaudeOAuth.get_valid_access_token() do
            {:ok, _token} ->
              :ok

            {:error, _} ->
              IO.puts(
                "⚠️ Claude Code OAuth token expired. Run /claude-code-auth to re-authenticate."
              )
          end
        end

      _ ->
        :ok
    end
  end

  @doc false
  def _custom_help do
    [
      {"claude-code-auth", "Authenticate with Claude Code via OAuth and import available models"},
      {"claude-code-status",
       "Check Claude Code OAuth authentication status and configured models"},
      {"claude-code-logout", "Remove Claude Code OAuth tokens and imported models"}
    ]
  end

  @doc false
  def _handle_custom_command(_command, name) do
    case name do
      "claude-code-auth" ->
        IO.puts("Starting Claude Code OAuth authentication…")

        case ClaudeOAuth.run_oauth_flow() do
          :ok ->
            IO.puts("✅ Claude Code OAuth authentication complete")

          {:error, reason} ->
            IO.puts("❌ Claude Code OAuth failed: #{inspect(reason)}")
        end

        true

      "claude-code-status" ->
        case ClaudeOAuth.load_tokens() do
          {:ok, tokens} when is_map_key(tokens, "access_token") ->
            IO.puts("✅ Claude Code OAuth: Authenticated")
            expires_at = tokens["expires_at"]

            if expires_at do
              remaining = max(0, trunc(expires_at - System.system_time(:second)))
              hours = div(remaining, 3600)
              minutes = div(rem(remaining, 3600), 60)
              IO.puts("Token expires in ~#{hours}h #{minutes}m")
            end

          _ ->
            IO.puts("🔓 Claude Code OAuth: Not authenticated")
            IO.puts("Run /claude-code-auth to begin the browser sign-in flow.")
        end

        true

      "claude-code-logout" ->
        path = ClaudeOAuth.token_storage_path()

        if File.exists?(path) do
          Isolation.safe_rm!(path)
          IO.puts("Removed Claude Code OAuth tokens")
        end

        case ClaudeOAuth.remove_models() do
          {:ok, count} when count > 0 ->
            IO.puts("Removed #{count} Claude Code models from configuration")

          {:ok, 0} ->
            :ok

          {:error, reason} ->
            IO.puts("Failed to remove models: #{inspect(reason)}")
        end

        IO.puts("✅ Claude Code logout complete")
        true

      _ ->
        nil
    end
  end

  @doc false
  def _register_model_types do
    [
      %{type: "claude_code", handler: &__MODULE__.create_model/3}
    ]
  end

  @doc false
  def create_model(model_name, model_config, _config) do
    IO.puts("Creating Claude Code model: #{model_name}")

    case ClaudeOAuth.get_valid_access_token() do
      {:ok, access_token} ->
        custom_endpoint = Map.get(model_config, "custom_endpoint", %{})

        _updated_model_config =
          Map.put(
            model_config,
            "custom_endpoint",
            Map.put(custom_endpoint, "api_key", access_token)
          )

        %{type: "claude_code", name: model_name, api_key: access_token}

      {:error, _reason} ->
        IO.puts("⚠️ No valid access token for Claude Code model #{model_name}")
        nil
    end
  end
end
