defmodule CodePuppyControl.CLI.SlashCommands.Commands.UC do
  @moduledoc """
  UC slash command: /uc [subcommand] [args].

  Manages Universal Constructor tools from the CLI. Provides a simplified
  text-based interface (not the full TUI from the Python version).

  Ports the Python `/uc` command from `code_puppy/command_line/uc_menu.py`.

  ## Usage

    /uc                          — list all UC tools with enabled/disabled status
    /uc toggle <tool_name>       — toggle a tool's enabled/disabled status
    /uc info <tool_name>         — show tool details (description, source path)
  """

  alias CodePuppyControl.Tools.UniversalConstructor.Registry, as: UCRegistry

  @doc """
  Handles `/uc` — lists all UC tools.

  Handles `/uc toggle <tool_name>` — toggles a tool's enabled flag.

  Handles `/uc info <tool_name>` — shows detailed info for a tool.
  """
  @spec handle_uc(String.t(), any()) :: {:continue, any()}
  def handle_uc(line, state) do
    case extract_args(line) |> String.trim() do
      "" ->
        list_tools()

      args ->
        parts = String.split(args, ~r/\s+/, trim: true)

        case parts do
          ["toggle", tool_name] ->
            toggle_tool(tool_name)

          ["info", tool_name] ->
            show_tool_info(tool_name)

          _more ->
            print_usage()
        end
    end

    {:continue, state}
  end

  # ── Subcommands ──────────────────────────────────────────────────────

  defp list_tools do
    tools = UCRegistry.list_tools(include_disabled: true)
    enabled_count = Enum.count(tools, & &1.meta.enabled)
    total_count = length(tools)

    IO.puts("")

    IO.puts("    #{IO.ANSI.bright()}Universal Constructor Tools#{IO.ANSI.reset()}")

    IO.puts("")

    if total_count == 0 do
      IO.puts("    #{IO.ANSI.yellow()}No UC tools found.#{IO.ANSI.reset()}")

      IO.puts(
        "    #{IO.ANSI.faint()}Ask the LLM to create one with universal_constructor!#{IO.ANSI.reset()}"
      )
    else
      IO.puts(
        "    #{IO.ANSI.faint()}#{enabled_count} enabled of #{total_count} total#{IO.ANSI.reset()}"
      )

      IO.puts("")

      Enum.each(tools, fn tool ->
        status =
          if tool.meta.enabled do
            "#{IO.ANSI.green()}[on]#{IO.ANSI.reset()}"
          else
            "#{IO.ANSI.red()}[off]#{IO.ANSI.reset()}"
          end

        namespace_tag =
          if tool.meta.namespace != "" do
            " #{IO.ANSI.faint()}(#{tool.meta.namespace})#{IO.ANSI.reset()}"
          else
            ""
          end

        IO.puts(
          "    #{status}  #{IO.ANSI.cyan()}#{tool.full_name}#{IO.ANSI.reset()}#{namespace_tag}"
        )
      end)
    end

    IO.puts("")

    IO.puts(
      "    #{IO.ANSI.faint()}Use /uc toggle <name> to enable/disable, /uc info <name> for details#{IO.ANSI.reset()}"
    )

    IO.puts("")
  end

  defp toggle_tool(tool_name) do
    tool = UCRegistry.get_tool(tool_name)

    case tool do
      nil ->
        IO.puts(
          IO.ANSI.red() <>
            "    Unknown tool: '#{tool_name}'" <> IO.ANSI.reset()
        )

      _tool ->
        source_path = tool.source_path

        case toggle_enabled_in_source(source_path, tool.meta.enabled) do
          :ok ->
            new_enabled = not tool.meta.enabled
            status = if new_enabled, do: "enabled", else: "disabled"

            # Reload the registry so the change is reflected
            UCRegistry.reload()

            IO.puts("")

            IO.puts(
              "    Tool '#{IO.ANSI.cyan()}#{tool_name}#{IO.ANSI.reset()}' is now #{IO.ANSI.green()}#{status}#{IO.ANSI.reset()}"
            )

            IO.puts("")

          {:error, reason} ->
            IO.puts(
              IO.ANSI.red() <>
                "    Failed to toggle tool: #{reason}" <> IO.ANSI.reset()
            )
        end
    end
  end

  defp show_tool_info(tool_name) do
    tool = UCRegistry.get_tool(tool_name)

    case tool do
      nil ->
        IO.puts(
          IO.ANSI.red() <>
            "    Unknown tool: '#{tool_name}'" <> IO.ANSI.reset()
        )

      _tool ->
        meta = tool.meta

        IO.puts("")

        IO.puts(
          "    #{IO.ANSI.bright()}Tool: #{IO.ANSI.cyan()}#{tool.full_name}#{IO.ANSI.reset()}"
        )

        IO.puts("")

        IO.puts("    #{IO.ANSI.bright()}Name:#{IO.ANSI.reset()}         #{meta.name}")

        namespace_display =
          if meta.namespace != "", do: meta.namespace, else: "(none)"

        IO.puts("    #{IO.ANSI.bright()}Namespace:#{IO.ANSI.reset()}    #{namespace_display}")

        status =
          if meta.enabled do
            "#{IO.ANSI.green()}ENABLED#{IO.ANSI.reset()}"
          else
            "#{IO.ANSI.red()}DISABLED#{IO.ANSI.reset()}"
          end

        IO.puts("    #{IO.ANSI.bright()}Status:#{IO.ANSI.reset()}      #{status}")
        IO.puts("    #{IO.ANSI.bright()}Version:#{IO.ANSI.reset()}     #{meta.version}")

        if meta.author != "" do
          IO.puts("    #{IO.ANSI.bright()}Author:#{IO.ANSI.reset()}      #{meta.author}")
        end

        IO.puts(
          "    #{IO.ANSI.bright()}Signature:#{IO.ANSI.reset()}   #{IO.ANSI.yellow()}#{tool.signature}#{IO.ANSI.reset()}"
        )

        IO.puts("")

        IO.puts("    #{IO.ANSI.bright()}Description:#{IO.ANSI.reset()}")

        IO.puts("    #{IO.ANSI.faint()}#{meta.description}#{IO.ANSI.reset()}")

        IO.puts("")

        IO.puts("    #{IO.ANSI.bright()}Source:#{IO.ANSI.reset()}")

        IO.puts("    #{IO.ANSI.faint()}#{tool.source_path}#{IO.ANSI.reset()}")

        IO.puts("")
    end
  end

  defp print_usage do
    IO.puts("")

    IO.puts(
      IO.ANSI.yellow() <>
        "    Usage: /uc [toggle <name> | info <name>]" <> IO.ANSI.reset()
    )

    IO.puts("    #{IO.ANSI.faint()}Use /uc without arguments to list all tools#{IO.ANSI.reset()}")

    IO.puts("")
  end

  # ── Source File Manipulation ──────────────────────────────────────────

  defp toggle_enabled_in_source(source_path, current_enabled) do
    case File.read(source_path) do
      {:ok, content} ->
        new_enabled = not current_enabled
        new_value = to_string(new_enabled)

        # Match enabled: true/false or enabled: True/False in @uc_tool map
        pattern = ~r/(enabled:\s*)(true|false|True|False)/

        case Regex.replace(pattern, content, fn _full, prefix, _old_value ->
               prefix <> new_value
             end) do
          ^content ->
            # No replacement made — enabled field not found
            {:error, "Could not find 'enabled:' field in @uc_tool at #{source_path}"}

          new_content ->
            case File.write(source_path, new_content) do
              :ok -> :ok
              {:error, reason} -> {:error, "Failed to write file: #{inspect(reason)}"}
            end
        end

      {:error, reason} ->
        {:error, "Could not read source file: #{inspect(reason)}"}
    end
  end

  # ── Helpers ───────────────────────────────────────────────────────────

  @spec extract_args(String.t()) :: String.t()
  defp extract_args("/" <> rest) do
    case String.split(rest, " ", parts: 2) do
      [_name] -> ""
      [_name, args] -> args
    end
  end

  defp extract_args(_line), do: ""
end
