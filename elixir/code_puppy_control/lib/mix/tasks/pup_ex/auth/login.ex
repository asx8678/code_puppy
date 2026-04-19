defmodule Mix.Tasks.PupEx.Auth.Login do
  @shortdoc "Stub: scaffold auth directory for Elixir pup-ex (full OAuth in bd-166)"
  @moduledoc """
  Initialize the auth directory for Elixir pup-ex.

  This is a STUB for bd-166 (full OAuth flow). It creates the
  `~/.code_puppy_ex/auth/` directory and a placeholder file to prove
  the isolation guard works end-to-end for auth paths.

  ## What it does

  1. Creates `~/.code_puppy_ex/auth/` (via isolation-safe mkdir)
  2. Writes a placeholder file explaining the directory's purpose
  3. Prints a message directing users to bd-166 for full OAuth

  ## What it does NOT do

  - Does NOT read or write anything under `~/.code_puppy/auth/`
  - Does NOT implement any OAuth flow
  - Does NOT share credentials with the Python pup

  Run `mix pup_ex.auth.login` again after bd-166 lands to authenticate.
  """
  use Mix.Task

  @requirements ["app.config"]

  @placeholder_content """
  This directory is reserved for pup-ex OAuth credentials.
  Full OAuth flow is tracked in bd-166.

  pup-ex will NEVER read credentials from ~/.code_puppy/auth/.
  Run `mix pup_ex.auth.login` again after bd-166 lands to authenticate.
  """

  @impl Mix.Task
  def run(_args) do
    alias CodePuppyControl.Config.{Isolation, Paths}

    auth_dir = Path.join(Paths.home_dir(), "auth")
    placeholder_path = Path.join(auth_dir, ".placeholder")

    try do
      Isolation.safe_mkdir_p!(auth_dir)
      Isolation.safe_write!(placeholder_path, @placeholder_content)

      Mix.shell().info(
        "Auth scaffolding initialized at #{auth_dir}/. Full OAuth flow lands with bd-166."
      )
    rescue
      e in Isolation.IsolationViolation ->
        Mix.shell().error("Isolation violation: #{Exception.message(e)}")
        Mix.shell().error("Cannot write to auth directory — check PUP_EX_HOME setting.")

      e ->
        Mix.shell().error("Failed to initialize auth directory: #{Exception.message(e)}")
    end
  end
end
