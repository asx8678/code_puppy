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
            nil ->
              IO.puts("⚠️ Claude Code OAuth token expired. Run /claude-code-auth to re-authenticate.")
            _token ->
              :ok
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
      {"claude-code-status", "Check Claude Code OAuth authentication status and configured models"},
      {"claude-code-logout", "Remove Claude Code OAuth tokens and imported models"}
    ]
  end

  @doc false
  def _handle_custom_command(_command, name) do
    case name do
      "claude-code-auth" ->
        IO.puts("Starting Claude Code OAuth authentication…")
        # TODO(bd-287): Implement full PKCE browser flow
        IO.puts("🐾 OAuth browser flow not yet implemented in Elixir. Track bd-287 for updates.")
        :handled

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
        :handled

      "claude-code-logout" ->
        path = ClaudeOAuth.token_storage_path()
        if File.exists?(path) do
          File.rm!(path)
          IO.puts("Removed Claude Code OAuth tokens")
        end
        removed = ClaudeOAuth.remove_models()
        IO.puts("Removed #{removed} Claude Code models from configuration")
        IO.puts("✅ Claude Code logout complete")
        :handled

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
    # TODO(bd-287): Full model creation with ClaudeCacheAsyncClient
    # For now, return a placeholder that will be wired when the full
    # LLM provider integration lands.
    IO.puts("Creating Claude Code model: #{model_name}")
    access_token = ClaudeOAuth.get_valid_access_token()
    if access_token do
      %{type: "claude_code", name: model_name, api_key: access_token}
    else
      IO.puts("⚠️ No valid access token for Claude Code model #{model_name}")
      nil
    end
  end
end
