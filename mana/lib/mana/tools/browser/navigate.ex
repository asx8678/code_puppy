defmodule Mana.Tools.Browser.Navigate do
  @moduledoc """
  Tool for navigating the browser to a URL.

  Delegates to `Mana.Tools.Browser.Manager.execute/2` which communicates
  with the Playwright bridge via the JSON-RPC protocol.

  ## Examples

      {:ok, %{"url" => "https://example.com", "title" => "Example"}} =
        Mana.Tools.Browser.Navigate.execute(%{"url" => "https://example.com"})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Browser.Manager
  alias Mana.Tools.Browser.Protocol

  @impl true
  def name, do: "browser_navigate"

  @impl true
  def description do
    "Navigate the browser to a specific URL. Returns the final URL and page title."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        url: %{
          type: "string",
          description: "The URL to navigate to (must include protocol like https://)"
        },
        wait_until: %{
          type: "string",
          description: "Wait until this load state: 'domcontentloaded', 'load', or 'networkidle'",
          default: "domcontentloaded"
        },
        timeout: %{
          type: "integer",
          description: "Navigation timeout in milliseconds",
          default: 30_000
        }
      },
      required: ["url"]
    }
  end

  @impl true
  def execute(args) do
    url = Map.fetch!(args, "url")
    wait_until = Map.get(args, "wait_until", "domcontentloaded")
    timeout = Map.get(args, "timeout", 30_000)

    params = Protocol.navigate_command(url, wait_until: wait_until, timeout: timeout)

    case Manager.execute("navigate", params) do
      {:ok, result} -> {:ok, result}
      {:error, reason} -> {:error, "Navigation failed: #{reason}"}
    end
  rescue
    _e in KeyError ->
      {:error, "Missing required parameter: url"}
  end
end
