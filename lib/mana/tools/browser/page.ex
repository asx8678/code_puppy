defmodule Mana.Tools.Browser.Page do
  @moduledoc """
  Tools for managing browser pages (tabs).

  Provides two operations:
  - **New page**: Open a new browser tab, optionally navigating to a URL
  - **List pages**: List all open browser pages with their URLs and titles

  Each operation is a separate Behaviour module.

  ## Examples

      {:ok, %{"page_id" => 2, "url" => "https://example.com"}} =
        Mana.Tools.Browser.Page.New.execute(%{"url" => "https://example.com"})

      {:ok, %{"pages" => [%{"url" => "https://google.com", "title" => "Google"}]}} =
        Mana.Tools.Browser.Page.List.execute(%{})
  """

  # ---------------------------------------------------------------------------
  # New page
  # ---------------------------------------------------------------------------

  defmodule New do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    alias Mana.Tools.Browser.Manager

    @impl true
    def name, do: "browser_new_page"

    @impl true
    def description do
      "Create a new browser page/tab. Optionally navigate to a URL."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          url: %{
            type: "string",
            description: "Optional URL to navigate to in the new page"
          }
        },
        required: []
      }
    end

    @impl true
    def execute(args) do
      params = %{"action" => "new"}
      params = if url = Map.get(args, "url"), do: Map.put(params, "url", url), else: params

      case Manager.execute("page", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Failed to create new page: #{reason}"}
      end
    end
  end

  # ---------------------------------------------------------------------------
  # List pages
  # ---------------------------------------------------------------------------

  defmodule List do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    alias Mana.Tools.Browser.Manager

    @impl true
    def name, do: "browser_list_pages"

    @impl true
    def description do
      "List all open browser pages/tabs with their URLs and titles."
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
      case Manager.execute("page", %{"action" => "list"}) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Failed to list pages: #{reason}"}
      end
    end
  end
end
