defmodule Mana.Prompt.Identity do
  @moduledoc """
  Identity block generator for system prompts.

  Provides the tool/capability identity block that describes
  Mana as an AI assistant with access to various tools.
  """

  @doc """
  Returns the identity block describing Mana's capabilities.

  ## Examples

      iex> block = Mana.Prompt.Identity.block()
      iex> String.contains?(block, "Mana")
      true

  """
  @spec block() :: String.t()
  def block do
    """
    ## Identity
    You are Mana, an AI assistant powered by an Elixir/OTP agent orchestration system.
    You have access to file operations, shell commands, and various tools.
    """
  end
end
