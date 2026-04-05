defmodule Mana.Banner do
  @moduledoc "ASCII art banner for Mana startup"

  @banner """
  ███╗   ███╗ █████╗ ███╗   ██╗ █████╗
  ████╗ ████║██╔══██╗████╗  ██║██╔══██╗
  ██╔████╔██║███████║██╔██╗ ██║███████║
  ██║╚██╔╝██║██╔══██║██║╚██╗██║██╔══██║
  ██║ ╚═╝ ██║██║  ██║██║ ╚████║██║  ██║
  ╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝  ╚═╝
  """

  @doc "Return the banner string with ANSI colors"
  @spec render() :: String.t()
  def render do
    IO.ANSI.format([:bright, :cyan, @banner, :reset, "\n"])
    |> to_string()
  end

  @doc "Return a smaller banner for compact displays"
  @spec render_compact() :: String.t()
  def render_compact do
    IO.ANSI.format([:bright, :cyan, " Mana ", :reset])
    |> to_string()
  end

  @doc "Print the banner to stdout. No-op in headless environments."
  @spec print() :: :ok
  def print do
    if tty_available?() do
      IO.puts(render())
    end

    :ok
  end

  # Check if a TTY is available for output.
  defp tty_available? do
    try do
      case :io.columns(:standard_io) do
        {:ok, _} -> true
        {:error, _} -> false
      end
    rescue
      ArgumentError -> false
    end
  end

  @doc "Return version info line with banner"
  @spec with_version(String.t()) :: String.t()
  def with_version(version) do
    banner = IO.ANSI.format([:bright, :cyan, @banner, :reset]) |> to_string()
    version_line = IO.ANSI.format([:faint, "  v#{version}", :reset]) |> to_string()
    "#{banner}\n#{version_line}\n"
  end
end
