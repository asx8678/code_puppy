defmodule Mana.Tools.Browser.Hover do
  @moduledoc """
  Tool for hovering over an element in the browser.

  Simulates a mouse hover over the targeted element, which is useful for
  triggering hover menus, tooltips, and CSS `:hover` states.

  Delegates to `Mana.Tools.Browser.Manager.execute/2`.

  ## Examples

      {:ok, %{\"success\" => true}} =
        Mana.Tools.Browser.Hover.execute(%{"selector" => "#menu-item"})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Browser.Manager

  @impl true
  def name, do: "browser_hover"

  @impl true
  def description do
    "Hover over an element in the browser. " <>
      "Triggers mouse hover events, useful for menus, tooltips, and :hover states."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        selector: %{
          type: "string",
          description: "CSS or XPath selector for the element to hover over"
        },
        timeout: %{
          type: "integer",
          description: "Timeout in milliseconds to wait for element",
          default: 10_000
        },
        force: %{
          type: "boolean",
          description: "Skip actionability checks and force the hover",
          default: false
        },
        modifiers: %{
          type: "array",
          items: %{type: "string"},
          description: "Modifier keys to hold during hover (e.g. [\"Shift\", \"Control\"])",
          default: []
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
    modifiers = Map.get(args, "modifiers", [])

    params = %{
      "selector" => selector,
      "timeout" => timeout,
      "force" => force,
      "modifiers" => modifiers
    }

    case Manager.execute("hover", params) do
      {:ok, result} -> {:ok, result}
      {:error, reason} -> {:error, "Hover failed: #{reason}"}
    end
  rescue
    _e in KeyError ->
      {:error, "Missing required parameter: selector"}
  end
end
