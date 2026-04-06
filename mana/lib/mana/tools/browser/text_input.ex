defmodule Mana.Tools.Browser.TextInput do
  @moduledoc """
  Tools for text operations on browser elements.

  Provides three operations:
  - **Set text**: Fill an input/textarea with text, optionally clearing first
  - **Get text**: Read the visible text content of an element
  - **Get value**: Read the current value of a form element (input, select, textarea)

  Each operation is a separate Behaviour module.

  ## Examples

      {:ok, %{\"success\" => true}} =
        Mana.Tools.Browser.TextInput.SetText.execute(%{
          "selector" => "#email",
          "text" => "user@example.com"
        })

      {:ok, %{\"text\" => \"Hello world\"}} =
        Mana.Tools.Browser.TextInput.GetText.execute(%{"selector" => "#output"})

      {:ok, %{\"value\" => \"current-value\"}} =
        Mana.Tools.Browser.TextInput.GetValue.execute(%{"selector" => "#input"})
  """

  alias Mana.Tools.Browser.Manager
  alias Mana.Tools.Browser.Protocol

  # ---------------------------------------------------------------------------
  # Set text (type/fill)
  # ---------------------------------------------------------------------------

  defmodule SetText do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_set_text"

    @impl true
    def description do
      "Set the text value of an input, textarea, or contenteditable element. " <>
        "Optionally clears existing content first."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          selector: %{
            type: "string",
            description: "CSS or XPath selector for the target input element"
          },
          text: %{
            type: "string",
            description: "The text to type into the element"
          },
          clear_first: %{
            type: "boolean",
            description: "Whether to clear existing content before typing",
            default: true
          },
          timeout: %{
            type: "integer",
            description: "Timeout in milliseconds to wait for element",
            default: 10_000
          }
        },
        required: ["selector", "text"]
      }
    end

    @impl true
    def execute(args) do
      selector = Map.fetch!(args, "selector")
      text = Map.fetch!(args, "text")
      clear_first = Map.get(args, "clear_first", true)
      timeout = Map.get(args, "timeout", 10_000)

      params = Protocol.type_command(selector, text, clear_first: clear_first, timeout: timeout)

      case Manager.execute("type", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Set text failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: selector and text are required"}
    end
  end

  # ---------------------------------------------------------------------------
  # Get text content
  # ---------------------------------------------------------------------------

  defmodule GetText do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_get_text"

    @impl true
    def description do
      "Get the visible text content of an element. Returns the innerText of the matched element."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          selector: %{
            type: "string",
            description: "CSS or XPath selector for the element"
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
        "method" => "text",
        "selector" => selector,
        "timeout" => timeout
      }

      case Manager.execute("get_content", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Get text failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: selector"}
    end
  end

  # ---------------------------------------------------------------------------
  # Get form element value
  # ---------------------------------------------------------------------------

  defmodule GetValue do
    @moduledoc false
    @behaviour Mana.Tools.Behaviour

    @impl true
    def name, do: "browser_get_value"

    @impl true
    def description do
      "Get the current value of a form element (input, select, textarea). " <>
        "Returns the `value` property of the matched element."
    end

    @impl true
    def parameters do
      %{
        type: "object",
        properties: %{
          selector: %{
            type: "string",
            description: "CSS or XPath selector for the form element"
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
        "method" => "value",
        "selector" => selector,
        "timeout" => timeout
      }

      case Manager.execute("get_content", params) do
        {:ok, result} -> {:ok, result}
        {:error, reason} -> {:error, "Get value failed: #{reason}"}
      end
    rescue
      _e in KeyError ->
        {:error, "Missing required parameter: selector"}
    end
  end
end
