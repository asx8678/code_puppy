defmodule Mana.Tools.Browser.ExecuteJs do
  @moduledoc """
  Tool for executing arbitrary JavaScript in the browser page context.

  Runs JavaScript code in the active page and returns the result.
  The script must return a JSON-serializable value (via `return` statement
  or as the last expression).

  Delegates to `Mana.Tools.Browser.Manager.execute/2`.

  ## Examples

      {:ok, %{"result" => 42}} =
        Mana.Tools.Browser.ExecuteJs.execute(%{"script" => "return 6 * 7"})

      {:ok, %{"result" => "Example"}} =
        Mana.Tools.Browser.ExecuteJs.execute(%{"script" => "return document.title"})
  """

  @behaviour Mana.Tools.Behaviour

  alias Mana.Tools.Browser.Manager

  @impl true
  def name, do: "browser_execute_js"

  @impl true
  def description do
    "Execute arbitrary JavaScript in the browser page context. " <>
      "Returns the result of the script execution. " <>
      "Use `return` to return a value. The script runs in the page's main frame."
  end

  @impl true
  def parameters do
    %{
      type: "object",
      properties: %{
        script: %{
          type: "string",
          description: "JavaScript code to execute. Use `return` to return a value."
        },
        args: %{
          type: "array",
          items: %{type: "string"},
          description: "Optional arguments to pass to the script. Access via `arguments[0]`, `arguments[1]`, etc.",
          default: []
        },
        timeout: %{
          type: "integer",
          description: "Execution timeout in milliseconds",
          default: 30_000
        }
      },
      required: ["script"]
    }
  end

  @impl true
  def execute(args) do
    script = Map.fetch!(args, "script")
    js_args = Map.get(args, "args", [])
    timeout = Map.get(args, "timeout", 30_000)

    params = %{
      "script" => script,
      "args" => js_args,
      "timeout" => timeout
    }

    case Manager.execute("execute_js", params) do
      {:ok, result} -> {:ok, result}
      {:error, reason} -> {:error, "JavaScript execution failed: #{reason}"}
    end
  rescue
    _e in KeyError ->
      {:error, "Missing required parameter: script"}
  end
end
