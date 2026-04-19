defmodule CodePuppyControl.CLI do
  @moduledoc """
  Elixir CLI entry point for `pup` / `code-puppy` commands.

  Preserves command-line compatibility with the Python implementation
  in `code_puppy.cli_runner`. Fast-path --help/--version avoid starting
  the full OTP application.

  ## Usage

      pup [OPTIONS] [PROMPT]
      code-puppy [OPTIONS] [PROMPT]

  ## Options

    * `-h`, `--help`        - Show help and exit
    * `-v`, `-V`, `--version` - Show version and exit
    * `-m`, `--model MODEL`  - Model to use (default: from config)
    * `-a`, `--agent AGENT`  - Agent to use (default: code-puppy)
    * `-c`, `--continue`     - Continue last session
    * `-p`, `--prompt PROMPT` - Execute a single prompt and exit
    * `-i`, `--interactive`   - Run in interactive mode
    * `--bridge-mode`        - Enable Mana LiveView TCP bridge
  """

  alias CodePuppyControl.CLI.Parser

  @version Mix.Project.config()[:version]

  @doc """
  Main entry point invoked by the escript wrapper.
  """
  @spec main([String.t()]) :: no_return()
  def main(args) do
    case Parser.parse(args) do
      {:help, _opts} ->
        IO.puts(help_text())
        System.halt(0)

      {:version, _opts} ->
        IO.puts("code-puppy #{@version}")
        System.halt(0)

      {:ok, opts} ->
        run(opts)

      {:error, message} ->
        IO.puts(:stderr, "Error: #{message}")
        IO.puts(:stderr, "Try 'pup --help' for usage information.")
        System.halt(1)
    end
  end

  @doc """
  Run the application with parsed options.

  Starts the OTP supervision tree (unless --help/--version) and
  delegates to the interactive loop or single-prompt runner.
  """
  @spec run(map()) :: no_return()
  def run(opts) do
    # Ensure the OTP app is started for full invocations
    Application.ensure_all_started(:code_puppy_control)

    case opts do
      %{prompt: prompt, interactive: true} ->
        # Interactive mode with initial prompt
        IO.puts("[cli] Starting interactive mode with prompt: #{prompt}")
        run_interactive(opts)

      %{prompt: prompt} when is_binary(prompt) and prompt != "" ->
        # Single prompt mode
        IO.puts("[cli] Running single prompt: #{prompt}")
        run_single_prompt(opts)

      %{continue: true} ->
        # Continue last session
        IO.puts("[cli] Continuing last session")
        run_interactive(opts)

      _ ->
        # Default: interactive mode
        run_interactive(opts)
    end

    System.halt(0)
  end

  # ---------------------------------------------------------------------------
  # Private helpers
  # ---------------------------------------------------------------------------

  defp run_interactive(opts) do
    # TODO(bd-172): Wire to CodePuppyControl interactive loop
    # Currently a placeholder that echoes intent.
    model = Map.get(opts, :model)
    agent = Map.get(opts, :agent, "code-puppy")

    if model do
      IO.puts("[cli] Interactive mode (agent=#{agent}, model=#{model})")
    else
      IO.puts("[cli] Interactive mode (agent=#{agent}, model=from config)")
    end

    IO.puts("[cli] Interactive loop not yet implemented - exiting")
  end

  defp run_single_prompt(opts) do
    # TODO(bd-172): Wire to CodePuppyControl prompt runner
    model = Map.get(opts, :model)
    prompt = opts[:prompt]

    IO.puts("[cli] Single prompt: #{prompt}")
    if model, do: IO.puts("[cli] Model override: #{model}")
    IO.puts("[cli] Prompt runner not yet implemented - exiting")
  end

  @doc """
  Generate help text matching the Python CLI format exactly.
  """
  @spec help_text() :: String.t()
  def help_text do
    """
    code-puppy #{@version} - AI-powered coding assistant

    Usage: pup [OPTIONS] [PROMPT]

    Options:
      -h, --help            Show this help message and exit
      -v, -V, --version     Show version and exit
      -m, --model MODEL     Model to use (default: from config)
      -a, --agent AGENT     Agent to use (default: code-puppy)
      -c, --continue        Continue last session
      -p, --prompt PROMPT   Execute a single prompt and exit
      -i, --interactive     Run in interactive mode
      --bridge-mode         Enable Mana LiveView TCP bridge

    Examples:
      pup                           Start interactive mode
      pup "explain this code"       Run single prompt
      pup -m claude-sonnet -c       Continue with specific model

    For more information: https://github.com/anthropics/code-puppy
    """
  end
end
