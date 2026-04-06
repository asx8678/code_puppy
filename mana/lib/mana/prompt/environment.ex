defmodule Mana.Prompt.Environment do
  @moduledoc """
  Environment context generator for system prompts.

  Provides system information including platform details, Elixir version,
  OTP release, current date, and working directory.
  """

  @doc """
  Returns the environment block with platform and runtime information.

  ## Examples

      iex> block = Mana.Prompt.Environment.block()
      iex> String.contains?(block, "Platform:")
      true

  """
  @spec block() :: String.t()
  def block do
    architecture = :erlang.system_info(:system_architecture) |> to_string()
    elixir_version = System.version()
    otp_release = :erlang.system_info(:otp_release) |> to_string()

    """
    ## Environment
    - Platform: #{architecture}
    - Elixir: #{elixir_version}
    - OTP: #{otp_release}
    """
  end

  @doc """
  Returns metadata block with current date and working directory.

  ## Parameters

    - opts: Keyword list of options
      - :cwd - Working directory (defaults to File.cwd!())
      - :date - Custom date (defaults to current UTC date)

  ## Examples

      iex> meta = Mana.Prompt.Environment.metadata_block(cwd: "/tmp")
      iex> String.contains?(meta, "Working directory: /tmp")
      true

  """
  @spec metadata_block(keyword()) :: String.t()
  def metadata_block(opts \\ []) do
    cwd = Keyword.get(opts, :cwd, File.cwd!())
    date = Keyword.get(opts, :date, Date.utc_today())
    date_str = Date.to_iso8601(date)

    """
    - Current date: #{date_str}
    - Working directory: #{cwd}
    """
  end
end
