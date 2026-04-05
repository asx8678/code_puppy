defmodule Mana.Commands.Colors do
  @moduledoc """
  Theme and color scheme management commands.

  Provides commands for viewing available color themes and switching
  between different color schemes for banners and UI elements.

  ## Commands

  - `/colors` - Show current color settings
  - `/colors list` - List available color themes
  - `/colors set <theme>` - Switch to a predefined theme
  - `/colors set <banner> <color>` - Set a specific banner color
  - `/colors banners` - List available banner types
  - `/colors reset` - Reset to default colors

  ## Examples

      /colors
      # Shows current color configuration

      /colors list
      # Shows: default, high-contrast, solarized-dark, solarized-light

      /colors set high-contrast
      # Switches to high-contrast theme

      /colors set banner_thinking blue
      # Sets THINKING banner to blue

      /colors reset
      # Resets all colors to defaults
  """

  @behaviour Mana.Commands.Behaviour

  alias Mana.Config.Store, as: ConfigStore

  # ANSI color codes
  @color_reset "\e[0m"

  # Predefined color themes
  @themes %{
    "default" => %{
      banner_thinking: "cyan",
      banner_shell: "blue",
      banner_file: "magenta",
      banner_agent: "green",
      banner_success: "green",
      banner_error: "red",
      banner_warning: "yellow",
      diff_addition: "green",
      diff_deletion: "red"
    },
    "high-contrast" => %{
      banner_thinking: "bright_white",
      banner_shell: "bright_blue",
      banner_file: "bright_magenta",
      banner_agent: "bright_green",
      banner_success: "bright_green",
      banner_error: "bright_red",
      banner_warning: "bright_yellow",
      diff_addition: "bright_green",
      diff_deletion: "bright_red"
    },
    "solarized-dark" => %{
      banner_thinking: "cyan",
      banner_shell: "blue",
      banner_file: "magenta",
      banner_agent: "green",
      banner_success: "green",
      banner_error: "orange1",
      banner_warning: "yellow",
      diff_addition: "green",
      diff_deletion: "orange1"
    },
    "solarized-light" => %{
      banner_thinking: "dark_cyan",
      banner_shell: "dark_blue",
      banner_file: "dark_magenta",
      banner_agent: "dark_green",
      banner_success: "dark_green",
      banner_error: "dark_red",
      banner_warning: "dark_orange",
      diff_addition: "dark_green",
      diff_deletion: "dark_orange"
    }
  }

  # Banner types
  @banner_types [
    {:banner_thinking, "THINKING", "Agent reasoning/thinking output"},
    {:banner_shell, "SHELL COMMAND", "Shell command execution"},
    {:banner_file, "FILE OPERATION", "File read/write operations"},
    {:banner_agent, "AGENT", "Agent status/messages"},
    {:banner_success, "SUCCESS", "Success messages"},
    {:banner_error, "ERROR", "Error messages"},
    {:banner_warning, "WARNING", "Warning messages"}
  ]

  # Available colors (subset of common Rich/ANSI colors)
  @available_colors [
    # Basic
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    # Bright
    "bright_black",
    "bright_red",
    "bright_green",
    "bright_yellow",
    "bright_blue",
    "bright_magenta",
    "bright_cyan",
    "bright_white",
    # Special
    "orange1",
    "orange3",
    "orange4",
    "deep_sky_blue1",
    "deep_sky_blue2",
    "deep_sky_blue3",
    "turquoise2",
    "turquoise4",
    "steel_blue1",
    "steel_blue3",
    "chartreuse1",
    "chartreuse2",
    "chartreuse3",
    "gold1",
    "gold3",
    "rosy_brown",
    "indian_red",
    # Dark variants
    "dark_cyan",
    "dark_blue",
    "dark_magenta",
    "dark_green",
    "dark_red",
    "dark_orange",
    "dark_yellow"
  ]

  @impl true
  def name, do: "/colors"

  @impl true
  def description, do: "Theme/color scheme picker"

  @impl true
  def usage, do: "/colors [list|set <theme>|set <banner> <color>|banners|reset]"

  @impl true
  def execute([], _context) do
    show_current_colors()
  end

  def execute(["list"], _context) do
    list_themes()
  end

  def execute(["set", theme], _context) when is_binary(theme) do
    set_theme(theme)
  end

  def execute(["set", banner, color], _context) do
    set_banner_color(banner, color)
  end

  def execute(["banners"], _context) do
    list_banners()
  end

  def execute(["reset"], _context) do
    reset_colors()
  end

  def execute(["colors"], _context) do
    list_available_colors()
  end

  def execute([unknown | _], _context) do
    {:error, "Unknown subcommand: #{unknown}. #{usage()}"}
  end

  # Implementation

  defp show_current_colors do
    lines =
      Enum.map(@banner_types, fn {key, name, desc} ->
        color = ConfigStore.get(key, default_color(key))
        preview = color_preview(color)
        "  #{preview} #{name}\n    Color: #{color} - #{desc}"
      end)

    diff_add = ConfigStore.get(:diff_addition_color, "green")
    diff_del = ConfigStore.get(:diff_deletion_color, "red")

    diff_section = """

    Diff highlighting:
      #{color_preview(diff_add)} Additions: #{diff_add}
      #{color_preview(diff_del)} Deletions: #{diff_del}
    """

    header = "Current color scheme:\n\n"
    footer = "\n\nUse '/colors list' to see available themes."

    {:ok, header <> Enum.join(lines, "\n") <> diff_section <> footer}
  end

  defp list_themes do
    lines =
      Enum.map(@themes, fn {name, _config} ->
        current = get_current_theme_name()
        marker = if name == current, do: " (current)", else: ""
        "  • #{name}#{marker}"
      end)

    header = "Available color themes:\n\n"

    footer = """

    Use '/colors set <theme>' to switch themes.
    Use '/colors set <banner> <color>' for custom colors.
    """

    {:ok, header <> Enum.join(lines, "\n") <> footer}
  end

  defp set_theme(theme_name) do
    case Map.get(@themes, theme_name) do
      nil ->
        known = Map.keys(@themes) |> Enum.join(", ")
        {:error, "Unknown theme: #{theme_name}\n\nAvailable themes: #{known}"}

      config ->
        Enum.each(config, fn {key, value} ->
          ConfigStore.put(key, to_string(value))
        end)

        {:ok, "Switched to theme: #{theme_name}\n\n#{count_changes(config)} color(s) applied."}
    end
  end

  defp set_banner_color(banner_name, color) do
    key = banner_to_key(banner_name)

    if is_nil(key) do
      known =
        @banner_types
        |> Enum.map(fn {k, _, _} -> k |> to_string() |> String.replace("banner_", "") end)
        |> Enum.join(", ")

      {:error, "Unknown banner: #{banner_name}\n\nAvailable banners: #{known}"}
    else
      if color in @available_colors do
        ConfigStore.put(key, color)
        {:ok, "Set #{key} to #{color} #{color_preview(color)}"}
      else
        known_sample = @available_colors |> Enum.take(8) |> Enum.join(", ")
        {:error, "Unknown color: #{color}\n\nTry: #{known_sample}, ...\nUse '/colors colors' for full list."}
      end
    end
  end

  defp list_banners do
    lines =
      Enum.map(@banner_types, fn {key, name, desc} ->
        color = ConfigStore.get(key, default_color(key))
        preview = color_preview(color)
        key_name = key |> to_string() |> String.replace("banner_", "")
        "  #{preview} #{name}\n    Key: #{key_name}, Color: #{color}\n    #{desc}"
      end)

    header = "Available banner types:\n\n"

    footer = """

    Set a banner color with:
      /colors set <banner> <color>

    Example:
      /colors set thinking bright_blue
    """

    {:ok, header <> Enum.join(lines, "\n\n") <> footer}
  end

  defp reset_colors do
    # Reset to default theme
    default = @themes["default"]

    Enum.each(default, fn {key, value} ->
      ConfigStore.put(key, to_string(value))
    end)

    {:ok, "Colors reset to default theme."}
  end

  defp list_available_colors do
    # Organize colors by category
    basic = ["black", "red", "green", "yellow", "blue", "magenta", "cyan", "white"]

    bright = [
      "bright_black",
      "bright_red",
      "bright_green",
      "bright_yellow",
      "bright_blue",
      "bright_magenta",
      "bright_cyan",
      "bright_white"
    ]

    format_section = fn title, colors ->
      lines = Enum.map(colors, fn c -> "  #{color_preview(c)} #{c}" end)
      "#{title}:\n" <> Enum.join(lines, "\n")
    end

    basic_section = format_section.("Basic colors", basic)
    bright_section = format_section.("Bright colors", bright)

    other = @available_colors -- (basic -- bright)
    other_section = format_section.("Other colors", other)

    {:ok, basic_section <> "\n\n" <> bright_section <> "\n\n" <> other_section}
  end

  # Helpers

  defp color_preview(color) do
    # Use Unicode block character to show color
    # Map common color names to ANSI codes for preview
    ansi = ansi_color_code(color)
    "#{ansi}████#{@color_reset}"
  end

  defp ansi_color_code("black"), do: "\e[30m"
  defp ansi_color_code("red"), do: "\e[31m"
  defp ansi_color_code("green"), do: "\e[32m"
  defp ansi_color_code("yellow"), do: "\e[33m"
  defp ansi_color_code("blue"), do: "\e[34m"
  defp ansi_color_code("magenta"), do: "\e[35m"
  defp ansi_color_code("cyan"), do: "\e[36m"
  defp ansi_color_code("white"), do: "\e[37m"
  defp ansi_color_code("bright_black"), do: "\e[90m"
  defp ansi_color_code("bright_red"), do: "\e[91m"
  defp ansi_color_code("bright_green"), do: "\e[92m"
  defp ansi_color_code("bright_yellow"), do: "\e[93m"
  defp ansi_color_code("bright_blue"), do: "\e[94m"
  defp ansi_color_code("bright_magenta"), do: "\e[95m"
  defp ansi_color_code("bright_cyan"), do: "\e[96m"
  defp ansi_color_code("bright_white"), do: "\e[97m"
  # Default to white
  defp ansi_color_code(_), do: "\e[37m"

  defp default_color(:banner_thinking), do: "cyan"
  defp default_color(:banner_shell), do: "blue"
  defp default_color(:banner_file), do: "magenta"
  defp default_color(:banner_agent), do: "green"
  defp default_color(:banner_success), do: "green"
  defp default_color(:banner_error), do: "red"
  defp default_color(:banner_warning), do: "yellow"
  defp default_color(_), do: "white"

  defp banner_to_key("thinking"), do: :banner_thinking
  defp banner_to_key("shell"), do: :banner_shell
  defp banner_to_key("file"), do: :banner_file
  defp banner_to_key("agent"), do: :banner_agent
  defp banner_to_key("success"), do: :banner_success
  defp banner_to_key("error"), do: :banner_error
  defp banner_to_key("warning"), do: :banner_warning
  defp banner_to_key("banner_thinking"), do: :banner_thinking
  defp banner_to_key("banner_shell"), do: :banner_shell
  defp banner_to_key("banner_file"), do: :banner_file
  defp banner_to_key("banner_agent"), do: :banner_agent
  defp banner_to_key("banner_success"), do: :banner_success
  defp banner_to_key("banner_error"), do: :banner_error
  defp banner_to_key("banner_warning"), do: :banner_warning
  defp banner_to_key(_), do: nil

  defp get_current_theme_name do
    colors =
      Enum.map(@themes["default"], fn {key, _} ->
        ConfigStore.get(key, default_color(key))
      end)

    # Try to match against known themes
    Enum.find_value(@themes, "custom", fn {name, config} ->
      theme_colors = Enum.map(config, fn {_, v} -> to_string(v) end)

      if theme_colors == colors, do: name, else: nil
    end)
  end

  defp count_changes(config), do: map_size(config)
end
