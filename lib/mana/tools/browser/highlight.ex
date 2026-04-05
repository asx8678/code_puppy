defmodule Mana.Tools.Browser.Highlight do
  @moduledoc """
  Tools for visually highlighting elements in the browser for debugging.

  Provides two operations:
  - **Highlight element**: Draw a colored outline around an element for visual identification
  - **Clear highlights**: Remove all visual highlights from the page

  Each operation is a separate Behaviour module.

  ## Examples

      {:ok, %{"success" => true}} =
        Mana.Tools.Browser.Highlight.HighlightElement.execute(%{
          "selector" => "#submit-btn",
          "color" => "red"
        })

      {:ok, %{"success" => true}} =
        Mana.Tools.Browser.Highlight.ClearHighlights.execute(%{})
  """

  alias Mana.Tools.Browser.Manager

  # ---------------------------------------------------------------------------
  # Highlight element
  # ---------------------------------------------------------------------------

  defmodule HighlightElement do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_highlight_element"

    @impl true
    def description do
      "Draw a colored outline around an element for visual debugging. " <>
        "Highlights the element so you can see exactly which element matches a selector."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          selector: %{
            type: "string",
            description: "CSS or XPath selector for the element to highlight"
          },
          color: %{
            type: "string",
            description: "Outline color for the highlight (CSS color name or hex)",
            default: "red"
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
      color = Map.get(args, "color", "red")
      timeout = Map.get(args, "timeout", 10_000)

      params = %{
        "action" => "highlight",
        "selector" => selector,
        "color" => color,
        "timeout" => timeout
      }

      case Manager.execute("highlight", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Highlight element failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: selector"}
    end
  end

  # ---------------------------------------------------------------------------
  # Clear highlights
  # ---------------------------------------------------------------------------

  defmodule ClearHighlights do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_clear_highlights"

    @impl true
    def description do
      "Remove all visual highlights from the page. " <>
        "Clears outline styling added by browser_highlight_element."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{},
        required: []
      }
    end

    @impl true
    def execute(_args) do
      case Manager.execute("highlight", %{"action" => "clear"}) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Clear highlights failed: #{reason}"}
      end
    end
  end
end
