defmodule Mana.Tools.Browser.Click do
  @moduledoc """
  Tool for clicking an element in the browser.

  Uses CSS selectors or XPath to locate the target element.
  Delegates to `Mana.Tools.Browser.Manager.execute/2`.

  ## Examples

      {:ok, %{"success" => true}} =
        Mana.Tools.Browser.Click.execute(%{"selector" => "#submit-btn"})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Browser.Manager
  alias Mana.Tools.Browser.Protocol

  @impl true
  def name, do: "browser_click"

  @impl true
  def description do
    "Click on an element in the browser using a CSS or XPath selector."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        selector: %{
          type: "string",
          description: "CSS or XPath selector for the element to click"
        },
        timeout: %{
          type: "integer",
          description: "Timeout in milliseconds to wait for element",
          default: 10_000
        },
        force: %{
          type: "boolean",
          description: "Skip actionability checks and force the click",
          default: false
        },
        button: %{
          type: "string",
          description: "Mouse button to click: 'left', 'right', or 'middle'",
          default: "left",
          enum: ["left", "right", "middle"]
        }
      },
      required: ["selector"]
    }
  end

  @impl true
  def execute(args) do
    selector = Map.fetch!(args, "selector")
    timeout = Map.get(args, "timeout", 10_000)
    force = Map.get(args, "force", false)
    button = Map.get(args, "button", "left")

    params =
      Protocol.click_command(selector,
        timeout: timeout,
        force: force,
        button: button
      )

    case Manager.execute("click", params) do
      {:ok, result} -> {:ok, result}
      {:error, reason} -> {:error, "Click failed: #{reason}"}
    end
  rescue
    _e in KeyError ->
      {:error, "Missing required parameter: selector"}
  end
end
