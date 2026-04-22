defmodule CodePuppyControl.Plugins.ChatGPTOAuth do
  @moduledoc """
  ChatGPT OAuth plugin.

  Provides browser-based OAuth authentication for ChatGPT Codex models,
  token refresh, and model discovery.

  Ported from Python: code_puppy/plugins/chatgpt_oauth/
  """

  use CodePuppyControl.Plugins.PluginBehaviour

  alias CodePuppyControl.Callbacks
  alias CodePuppyControl.Auth.ChatGPTOAuth

  @impl true
  def name, do: "chatgpt_oauth"

  @impl true
  def description, do: "ChatGPT OAuth authentication and model management"

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
    case ChatGPTOAuth.load_tokens() do
      {:ok, tokens} ->
        if tokens["access_token"] do
          case ChatGPTOAuth.get_valid_access_token() do
            nil ->
              IO.puts("⚠️ ChatGPT OAuth token expired. Run /chatgpt-auth to re-authenticate.")
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
      {"chatgpt-auth", "Authenticate with ChatGPT via OAuth and import available models"},
      {"chatgpt-status", "Check ChatGPT OAuth authentication status and configured models"},
      {"chatgpt-logout", "Remove ChatGPT OAuth tokens and imported models"}
    ]
  end

  @doc false
  def _handle_custom_command(_command, name) do
    case name do
      "chatgpt-auth" ->
        IO.puts("Starting ChatGPT OAuth authentication…")
        # TODO(bd-290): Implement full PKCE browser flow
        IO.puts("🐾 OAuth browser flow not yet implemented in Elixir. Track bd-290 for updates.")
        :handled

      "chatgpt-status" ->
        case ChatGPTOAuth.load_tokens() do
          {:ok, tokens} when is_map_key(tokens, "access_token") ->
            IO.puts("✅ ChatGPT OAuth: Authenticated")

          _ ->
            IO.puts("🔓 ChatGPT OAuth: Not authenticated")
            IO.puts("Run /chatgpt-auth to begin the browser sign-in flow.")
        end
        :handled

      "chatgpt-logout" ->
        path = ChatGPTOAuth.token_storage_path()
        if File.exists?(path) do
          File.rm!(path)
          IO.puts("Removed ChatGPT OAuth tokens")
        end
        removed = ChatGPTOAuth.remove_models()
        IO.puts("Removed #{removed} ChatGPT models from configuration")
        IO.puts("✅ ChatGPT logout complete")
        :handled

      _ ->
        nil
    end
  end

  @doc false
  def _register_model_types do
    [
      %{type: "chatgpt_oauth", handler: &__MODULE__.create_model/3}
    ]
  end

  @doc false
  def create_model(model_name, model_config, _config) do
    # TODO(bd-290): Full model creation with OpenAIResponsesModel
    IO.puts("Creating ChatGPT OAuth model: #{model_name}")
    access_token = ChatGPTOAuth.get_valid_access_token()
    if access_token do
      %{type: "chatgpt_oauth", name: model_name, api_key: access_token}
    else
      IO.puts("⚠️ No valid access token for ChatGPT model #{model_name}")
      nil
    end
  end
end
