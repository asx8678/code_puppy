defmodule Mana.Tools.Browser.Wait do
  @moduledoc """
  Tools for waiting on browser conditions.

  Provides two operations:
  - **Wait for element**: Wait until an element matching a selector appears in the DOM
  - **Wait for load**: Wait until the page reaches a specific load state

  Each operation is a separate Behaviour module.

  ## Examples

      {:ok, %{\"success\" => true}} =
        Mana.Tools.Browser.Wait.WaitForElement.execute(%{
          "selector" => "#results",
          "timeout" => 15_000
        })

      {:ok, %{\"status\" => \"networkidle\"}} =
        Mana.Tools.Browser.Wait.WaitForLoad.execute(%{"state" => "networkidle"})
  """

  alias Mana.Tools.Browser.Manager

  # ---------------------------------------------------------------------------
  # Wait for element
  # ---------------------------------------------------------------------------

  defmodule WaitForElement do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_wait_for_element"

    @impl true
    def description do
      "Wait for an element matching a selector to appear in the DOM. " <>
        "Useful for waiting until dynamic content is loaded and rendered."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          selector: %{
            type: "string",
            description: "CSS or XPath selector to wait for"
          },
          state: %{
            type: "string",
            description:
              "Element state to wait for: 'attached' (in DOM), 'visible' (visible), 'hidden' (hidden), or 'detached' (removed)",
            default: "visible",
            enum: ["attached", "visible", "hidden", "detached"]
          },
          timeout: %{
            type: "integer",
            description: "Maximum wait time in milliseconds",
            default: 30_000
          }
        },
        required: ["selector"]
      }
    end

    @impl true
    def execute(args) do
      selector = Map.fetch!(args, "selector")
      state = Map.get(args, "state", "visible")
      timeout = Map.get(args, "timeout", 30_000)

      params = %{
        "method" => "element",
        "selector" => selector,
        "state" => state,
        "timeout" => timeout
      }

      case Manager.execute("wait", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Wait for element failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: selector"}
    end
  end

  # ---------------------------------------------------------------------------
  # Wait for load state
  # ---------------------------------------------------------------------------

  defmodule WaitForLoad do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_wait_for_load"

    @impl true
    def description do
      "Wait for the page to reach a specific load state. " <>
        "States: 'domcontentloaded' (DOM ready), 'load' (all resources), 'networkidle' (no network activity)."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          state: %{
            type: "string",
            description: "Load state to wait for: 'domcontentloaded', 'load', or 'networkidle'",
            default: "domcontentloaded",
            enum: ["domcontentloaded", "load", "networkidle"]
          },
          timeout: %{
            type: "integer",
            description: "Maximum wait time in milliseconds",
            default: 30_000
          }
        },
        required: []
      }
    end

    @impl true
    def execute(args) do
      state = Map.get(args, "state", "domcontentloaded")
      timeout = Map.get(args, "timeout", 30_000)

      params = %{
        "method" => "load_state",
        "state" => state,
        "timeout" => timeout
      }

      case Manager.execute("wait", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Wait for load failed: #{reason}"}
      end
    end
  end
end
