defmodule Mana.Tools.Browser.Find do
  @moduledoc """
  Tools for finding elements in the browser page.

  Provides three finding strategies:
  - **By role**: Find elements by ARIA role (e.g. button, link, textbox, heading)
  - **By text**: Find elements containing specific text content
  - **By label**: Find elements by their accessible label text

  Each strategy is exposed as a separate tool for the agent, implemented
  as multiple Behaviour modules in this file.

  ## Examples

      {:ok, %{"elements" => [%{"role" => "button", "name" => "Submit"}]}} =
        Mana.Tools.Browser.Find.ByRole.execute(%{"role" => "button"})

      {:ok, %{"elements" => [%{"text" => "Click here", "tag" => "a"}]}} =
        Mana.Tools.Browser.Find.ByText.execute(%{"text" => "Click here"})
  """

  # ---------------------------------------------------------------------------
  # Find by ARIA role
  # ---------------------------------------------------------------------------

  defmodule ByRole do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    alias Mana.Tools.Browser.Manager

    @impl true
    def name, do: "browser_find_by_role"

    @impl true
    def description do
      "Find elements by ARIA role (recommended for accessibility). " <>
        "Roles include: button, link, textbox, heading, checkbox, radio, etc."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          role: %{
            type: "string",
            description: "ARIA role to search for (button, link, textbox, heading, etc.)"
          },
          name: %{
            type: "string",
            description: "Optional accessible name to filter by"
          },
          exact: %{
            type: "boolean",
            description: "Whether to match the name exactly",
            default: false
          },
          timeout: %{
            type: "integer",
            description: "Timeout in milliseconds to wait for elements",
            default: 10_000
          }
        },
        required: ["role"]
      }
    end

    @impl true
    def execute(args) do
      role = Map.fetch!(args, "role")

      params =
        %{
          "method" => "role",
          "role" => role,
          "name" => Map.get(args, "name"),
          "exact" => Map.get(args, "exact", false),
          "timeout" => Map.get(args, "timeout", 10_000)
        }
        |> Enum.reject(fn {_k, v} -> is_nil(v) end)
        |> Map.new()

      case Manager.execute("find", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Find by role failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: role"}
    end
  end

  # ---------------------------------------------------------------------------
  # Find by text content
  # ---------------------------------------------------------------------------

  defmodule ByText do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    alias Mana.Tools.Browser.Manager
    alias Mana.Tools.Browser.Protocol

    @impl true
    def name, do: "browser_find_by_text"

    @impl true
    def description do
      "Find elements containing specific text content. " <>
        "Useful for locating buttons, links, or headings by their visible text."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          text: %{
            type: "string",
            description: "Text to search for in elements"
          },
          exact: %{
            type: "boolean",
            description: "Whether to match text exactly",
            default: false
          },
          timeout: %{
            type: "integer",
            description: "Timeout in milliseconds to wait for elements",
            default: 10_000
          }
        },
        required: ["text"]
      }
    end

    @impl true
    def execute(args) do
      text = Map.fetch!(args, "text")
      exact = Map.get(args, "exact", false)
      timeout = Map.get(args, "timeout", 10_000)

      params =
        Protocol.find_text_command(text, exact: exact, timeout: timeout)
        |> Map.put("method", "text")

      case Manager.execute("find", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Find by text failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: text"}
    end
  end

  # ---------------------------------------------------------------------------
  # Find by accessible label
  # ---------------------------------------------------------------------------

  defmodule ByLabel do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    alias Mana.Tools.Browser.Manager

    @impl true
    def name, do: "browser_find_by_label"

    @impl true
    def description do
      "Find form elements by their associated label text. " <>
        "Matches inputs, selects, and textareas to their <label> elements."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          label: %{
            type: "string",
            description: "The label text associated with the target element"
          },
          exact: %{
            type: "boolean",
            description: "Whether to match the label exactly",
            default: false
          },
          timeout: %{
            type: "integer",
            description: "Timeout in milliseconds to wait for elements",
            default: 10_000
          }
        },
        required: ["label"]
      }
    end

    @impl true
    def execute(args) do
      label = Map.fetch!(args, "label")

      params = %{
        "method" => "label",
        "label" => label,
        "exact" => Map.get(args, "exact", false),
        "timeout" => Map.get(args, "timeout", 10_000)
      }

      case Manager.execute("find", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Find by label failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: label"}
    end
  end
end
