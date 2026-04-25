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

    * `-h`, `--help` - Show help and exit
    * `-v`, `-V`, `--version` - Show version and exit
    * `-m`, `--model MODEL` - Model to use (default: from config)
    * `-a`, `--agent AGENT` - Agent to use (default: code-puppy)
    * `-c`, `--continue` - Continue last session
    * `-p`, `--prompt PROMPT` - Execute a single prompt and exit
    * `-i`, `--interactive` - Run in interactive mode
    * `--bridge-mode` - Enable Mana LiveView TCP bridge
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
  Determine the run mode from parsed CLI opts.

  Returns an atom tag describing which execution path `run/1` will
  take, without starting the OTP supervision tree or calling
  `System.halt/1`.  Extracted for testability — the routing
  logic is pure and deterministic.

  ## Returns

    * `:one_shot`               — Non-interactive prompt (`-p TEXT` / positional)
    * `:interactive_with_prompt` — Interactive mode with an initial prompt (`-p TEXT -i`)
    * `:continue_session`       — Continue last session (`-c`)
    * `:interactive_default`     — Plain interactive REPL (no prompt / empty prompt)
  """
  @spec resolve_run_mode(map()) ::
          :one_shot | :interactive_with_prompt | :continue_session | :interactive_default
  def resolve_run_mode(opts) do
    case opts do
      %{prompt: _, interactive: true} ->
        :interactive_with_prompt

      %{prompt: prompt} when is_binary(prompt) and prompt != "" ->
        :one_shot

      %{continue: true} ->
        :continue_session

      _ ->
        :interactive_default
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

    case resolve_run_mode(opts) do
      :one_shot ->
        run_single_prompt(opts)

      :interactive_with_prompt ->
        run_interactive(opts)

      :continue_session ->
        run_interactive(opts)

      :interactive_default ->
        run_interactive(opts)
    end

    System.halt(0)
  end

  # ---------------------------------------------------------------------------
  # Private helpers
  # ---------------------------------------------------------------------------

  defp run_interactive(opts) do
    CodePuppyControl.REPL.Loop.run(opts)
  end

  defp run_single_prompt(opts) do
    case CodePuppyControl.REPL.OneShot.run(opts) do
      :ok ->
        :ok

      :error ->
        System.halt(1)
    end
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
      -h, --help Show this help message and exit
      -v, -V, --version Show version and exit
      -m, --model MODEL Model to use (default: from config)
      -a, --agent AGENT Agent to use (default: code-puppy)
      -c, --continue Continue last session
      -p, --prompt PROMPT Execute a single prompt and exit
      -i, --interactive Run in interactive mode
      --bridge-mode Enable Mana LiveView TCP bridge

    Examples:
      pup Start interactive mode
      pup "explain this code" Run single prompt
      pup -m claude-sonnet -c Continue with specific model

    For more information: https://github.com/anthropics/code-puppy
    """
  end
end
