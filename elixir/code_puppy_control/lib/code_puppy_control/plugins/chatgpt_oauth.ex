defmodule CodePuppyControl.Plugins.ChatGptOAuth do
  @moduledoc """
  ChatGPT OAuth plugin.

  Registers startup refresh behavior plus the `/chatgpt-auth`,
  `/chatgpt-status`, and `/chatgpt-logout` custom commands.

  The core OAuth flow and token/model management live in
  `CodePuppyControl.Auth.ChatGptOAuth`.
  """

  use CodePuppyControl.Plugins.PluginBehaviour

  alias CodePuppyControl.Auth.ChatGptOAuth
  alias CodePuppyControl.Callbacks

  @impl true
  def name, do: "chatgpt_oauth"

  @impl true
  def description, do: "ChatGPT OAuth authentication and model registration"

  @impl true
  def register do
    Callbacks.register(:startup, &__MODULE__.on_startup/0)
    Callbacks.register(:custom_command, &__MODULE__.handle_custom_command/2)
    Callbacks.register(:custom_command_help, &__MODULE__.custom_help/0)
    :ok
  end

  @doc false
  @spec on_startup() :: :ok
  def on_startup do
    tokens = ChatGptOAuth.load_stored_tokens()

    if tokens && Map.get(tokens, "access_token") do
      case ChatGptOAuth.get_valid_access_token() do
        {:ok, _} ->
          :ok

        {:error, _} ->
          IO.puts(
            :stderr,
            "Warning: ChatGPT OAuth token expired and refresh failed. Run /chatgpt-auth to re-authenticate."
          )

          :ok
      end
    else
      :ok
    end
  end

  @doc false
  @spec custom_help() :: [{String.t(), String.t()}]
  def custom_help do
    [
      {"chatgpt-auth", "Authenticate with ChatGPT via OAuth and import available models"},
      {"chatgpt-status", "Check ChatGPT OAuth authentication status and configured models"},
      {"chatgpt-logout", "Remove ChatGPT OAuth tokens and imported models"}
    ]
  end

  @doc false
  @spec handle_custom_command(String.t(), String.t()) :: true | nil
  def handle_custom_command(_command, name) when is_binary(name) do
    case name do
      "chatgpt-auth" ->
        ChatGptOAuth.run_oauth_flow()
        true

      "chatgpt-status" ->
        show_status()
        true

      "chatgpt-logout" ->
        do_logout()
        true

      _ ->
        nil
    end
  end

  def handle_custom_command(_command, _name), do: nil

  defp show_status do
    tokens = ChatGptOAuth.load_stored_tokens()

    if tokens && Map.get(tokens, "access_token") do
      IO.puts("ChatGPT OAuth: Authenticated")
      api_key = Map.get(tokens, "api_key")

      if api_key do
        IO.puts("OAuth access token available for API requests")
      else
        IO.puts("No access token obtained. Authentication may have failed.")
      end

      chatgpt_models = ChatGptOAuth.load_chatgpt_models()

      oauth_models =
        for {name, cfg} <- chatgpt_models,
            Map.get(cfg, "oauth_source") == "chatgpt-oauth-plugin",
            do: name

      if oauth_models != [] do
        IO.puts("Configured ChatGPT models: " <> Enum.join(oauth_models, ", "))
      else
        IO.puts("No ChatGPT models configured yet.")
      end
    else
      IO.puts("ChatGPT OAuth: Not authenticated")
      IO.puts("Run /chatgpt-auth to launch the browser sign-in flow.")
    end
  end

  defp do_logout do
    ChatGptOAuth.clear_stored_tokens()
    removed = ChatGptOAuth.remove_chatgpt_models()
    IO.puts("Removed ChatGPT OAuth tokens")

    if removed > 0,
      do:
        IO.puts("Removed " <> Integer.to_string(removed) <> " ChatGPT models from configuration")

    IO.puts("ChatGPT logout complete")
    :ok
  end
end
