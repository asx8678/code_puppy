defmodule Mana.Tools.Browser.Tools do
  @moduledoc """
  Plugin module that registers all browser tools via the `register_tools` hook.

  This module implements `Mana.Plugin.Behaviour` so that browser tools are
  automatically discovered and registered when the plugin system starts.

  ## Registered Tools

  - `browser_navigate` — Navigate to a URL
  - `browser_click` — Click an element by selector
  - `browser_screenshot_analyze` — Take a screenshot
  - `browser_find_by_role` — Find elements by ARIA role
  - `browser_find_by_text` — Find elements by text content
  - `browser_find_by_label` — Find elements by accessible label
  - `browser_new_page` — Open a new browser tab
  - `browser_list_pages` — List open browser tabs
  - `browser_hover` — Hover over an element
  - `browser_set_text` — Set text in an input element
  - `browser_get_text` — Get visible text content of an element
  - `browser_get_value` — Get the value of a form element
  - `browser_execute_js` — Execute arbitrary JavaScript
  - `browser_scroll` — Scroll the page or an element
  - `browser_scroll_to_element` — Scroll until an element is in view
  - `browser_wait_for_element` — Wait for an element to appear
  - `browser_wait_for_load` — Wait for a page load state
  - `browser_save_workflow` — Save a recorded workflow
  - `browser_list_workflows` — List saved workflows
  - `browser_read_workflow` — Read workflow steps
  - `browser_highlight_element` — Visually highlight an element
  - `browser_clear_highlights` — Remove all visual highlights

  ## Architecture

  The actual tool logic lives in the individual Behaviour modules under
  `Mana.Tools.Browser.*`. This plugin acts as the registration glue,
  ensuring the browser tools are available both via the Tools Registry
  (for agent execution) and via the plugin hook system (for discovery).

  ## Tool Modules

  Each tool module implements `Mana.Tools.Behaviour` and is also listed
  in `Mana.Tools.Registry`'s `@expected_tools` so that it participates
  in the ETS-backed fast lookup path.
  """

  @behaviour Mana.Plugin.Behaviour

  require Logger

  @tool_modules [
    Mana.Tools.Browser.Navigate,
    Mana.Tools.Browser.Click,
    Mana.Tools.Browser.Screenshot,
    Mana.Tools.Browser.Find.ByRole,
    Mana.Tools.Browser.Find.ByText,
    Mana.Tools.Browser.Find.ByLabel,
    Mana.Tools.Browser.Page.New,
    Mana.Tools.Browser.Page.List,
    # New browser tools
    Mana.Tools.Browser.Hover,
    Mana.Tools.Browser.TextInput.SetText,
    Mana.Tools.Browser.TextInput.GetText,
    Mana.Tools.Browser.TextInput.GetValue,
    Mana.Tools.Browser.ExecuteJs,
    Mana.Tools.Browser.Scroll.ScrollPage,
    Mana.Tools.Browser.Scroll.ScrollToElement,
    Mana.Tools.Browser.Wait.WaitForElement,
    Mana.Tools.Browser.Wait.WaitForLoad,
    Mana.Tools.Browser.Workflow.SaveWorkflow,
    Mana.Tools.Browser.Workflow.ListWorkflows,
    Mana.Tools.Browser.Workflow.ReadWorkflow,
    Mana.Tools.Browser.Highlight.HighlightElement,
    Mana.Tools.Browser.Highlight.ClearHighlights
  ]

  # ---------------------------------------------------------------------------
  # Plugin.Behaviour callbacks
  # ---------------------------------------------------------------------------

  @impl true
  def name, do: "browser_tools"

  @impl true
  def init(_config) do
    Logger.info("[#{__MODULE__}] Browser tools plugin initialized (#{length(@tool_modules)} tools)")
    {:ok, %{tools: @tool_modules}}
  end

  @impl true
  def hooks do
    [
      {:register_tools, &__MODULE__.on_register_tools/0},
      {:startup, &__MODULE__.on_startup/0}
    ]
  end

  @impl true
  def terminate do
    :ok
  end

  # ---------------------------------------------------------------------------
  # Hook handlers
  # ---------------------------------------------------------------------------

  @doc false
  def on_startup do
    # Ensure the browser tools are registered in the Tools.Registry.
    # They may already be registered via @expected_tools, but this provides
    # a safety net if the registry is started before the expected tools list
    # is updated.
    Enum.each(@tool_modules, fn module ->
      case Mana.Tools.Registry.register(module) do
        :ok ->
          :ok

        {:error, :already_registered} ->
          :ok

        {:error, reason} ->
          Logger.warning("[#{__MODULE__}] Failed to register #{inspect(module)}: #{inspect(reason)}")
      end
    end)

    :ok
  end

  @doc false
  def on_register_tools do
    Enum.map(@tool_modules, fn module ->
      %{
        name: module.name(),
        description: module.description(),
        parameters: module.parameters(),
        execute: &module.execute/1
      }
    end)
  end

  # ---------------------------------------------------------------------------
  # Public API
  # ---------------------------------------------------------------------------

  @doc """
  Returns the list of all browser tool module names.
  """
  @spec tool_modules() :: [module()]
  def tool_modules, do: @tool_modules

  @doc """
  Returns the list of browser tool names as strings.
  """
  @spec tool_names() :: [String.t()]
  def tool_names do
    Enum.map(@tool_modules, & &1.name())
  end
end
