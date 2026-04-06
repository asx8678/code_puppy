defmodule Mana.Tools.Browser.Screenshot do
  @moduledoc """
  Tool for taking a screenshot of the browser page.

  Returns base64-encoded image data that can be analyzed.
  Delegates to `Mana.Tools.Browser.Manager.execute/2`.

  ## Examples

      {:ok, %{"image" => "data:image/png;base64,iVBOR...", "full_page" => false}} =
        Mana.Tools.Browser.Screenshot.execute(%{})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Browser.Manager
  alias Mana.Tools.Browser.Protocol

  @impl true
  def name, do: "browser_screenshot_analyze"

  @impl true
  def description do
    "Take a screenshot of the browser page and return base64 image data. " <>
      "Optionally capture full page or a specific element."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        full_page: %{
          type: "boolean",
          description: "Capture full page (true) or just viewport (false)",
          default: false
        },
        element_selector: %{
          type: "string",
          description: "Optional CSS selector to screenshot a specific element"
        }
      },
      required: []
    }
  end

  @impl true
  def execute(args) do
    full_page = Map.get(args, "full_page", false)
    element_selector = Map.get(args, "element_selector")

    params =
      Protocol.screenshot_command(
        full_page: full_page,
        selector: element_selector
      )

    case Manager.execute("screenshot", params) do
      {:ok, %{"image" => _image_data} = result} ->
        {:ok, result}

      {:ok, result} ->
        # If the bridge returns a different structure, normalize it
        {:ok, result}

      {:error, reason} ->
        {:error, "Screenshot failed: #{reason}"}
    end
  end
end
