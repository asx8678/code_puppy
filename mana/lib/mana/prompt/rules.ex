defmodule Mana.Prompt.Rules do
  @moduledoc """
  Rules loader for system prompts.

  Loads AGENTS.md files from the specified working directory
  and formats them as a rules block for system prompts.
  """

  @doc """
  Loads the AGENTS.md file from the specified directory.

  ## Parameters

    - opts: Keyword list of options
      - :cwd - Directory to look for AGENTS.md (defaults to File.cwd!())

  ## Returns

    String containing the rules block, or empty string if no file found

  ## Examples

      iex> Mana.Prompt.Rules.load(cwd: ".")
      "## Rules\\n..."

  """
  @spec load(keyword()) :: String.t()
  def load(opts \\ []) do
    cwd = Keyword.get(opts, :cwd, File.cwd!())
    agents_file = Path.join(cwd, "AGENTS.md")

    case File.read(agents_file) do
      {:ok, content} -> "## Rules\n#{content}"
      {:error, _} -> ""
    end
  end
end
