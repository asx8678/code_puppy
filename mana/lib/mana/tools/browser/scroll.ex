defmodule Mana.Tools.Browser.Scroll do
  @moduledoc """
  Tools for scrolling the browser page or specific elements.

  Provides two operations:
  - **Scroll**: Scroll the page or a specific element in a direction
  - **Scroll to element**: Scroll until a specific element is in view

  Each operation is a separate Behaviour module.

  ## Examples

      {:ok, %{\"success\" => true}} =
        Mana.Tools.Browser.Scroll.ScrollPage.execute(%{"direction" => "down", "amount" => 5})

      {:ok, %{\"success\" => true}} =
        Mana.Tools.Browser.Scroll.ScrollToElement.execute(%{"selector" => "#footer"})
  """

  alias Mana.Tools.Browser.Manager
  alias Mana.Tools.Browser.Protocol

  # ---------------------------------------------------------------------------
  # Scroll page / element
  # ---------------------------------------------------------------------------

  defmodule ScrollPage do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_scroll"

    @impl true
    def description do
      "Scroll the page or a specific element in a given direction. " <>
        "Supports up, down, left, and right scrolling with configurable amount."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          direction: %{
            type: "string",
            description: "Scroll direction: 'up', 'down', 'left', or 'right'",
            default: "down",
            enum: ["up", "down", "left", "right"]
          },
          amount: %{
            type: "integer",
            description: "Scroll amount multiplier (1-10). Higher values scroll further.",
            default: 3,
            minimum: 1,
            maximum: 10
          },
          element_selector: %{
            type: "string",
            description: "Optional CSS selector to scroll a specific element instead of the page"
          }
        },
        required: []
      }
    end

    @impl true
    def execute(args) do
      direction = Map.get(args, "direction", "down")
      amount = Map.get(args, "amount", 3)
      element_selector = Map.get(args, "element_selector")

      params =
        Protocol.scroll_command(
          direction: direction,
          amount: amount,
          selector: element_selector
        )

      case Manager.execute("scroll", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Scroll failed: #{reason}"}
      end
    end
  end

  # ---------------------------------------------------------------------------
  # Scroll to element
  # ---------------------------------------------------------------------------

  defmodule ScrollToElement do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_scroll_to_element"

    @impl true
    def description do
      "Scroll the page until a specific element is brought into the viewport. " <>
        "Useful for bringing elements into view before interacting with them."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          selector: %{
            type: "string",
            description: "CSS or XPath selector for the element to scroll into view"
          },
          timeout: %{
            type: "integer",
            description: "Timeout in milliseconds to wait for element",
            default: 10_000
          }
        },
        required: ["selector"]
      }
    end

    @impl true
    def execute(args) do
      selector = Map.fetch!(args, "selector")
      timeout = Map.get(args, "timeout", 10_000)

      params = %{
        "method" => "scroll_into_view",
        "selector" => selector,
        "timeout" => timeout
      }

      case Manager.execute("scroll", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Scroll to element failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: selector"}
    end
  end
end
