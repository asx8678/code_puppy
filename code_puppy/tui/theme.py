"""Textual CSS theme for Code Puppy TUI.

Color palette based on the original CLI jewel-tone banner colors:
  - Deep sapphire blue (thinking/primary)
  - Amethyst purple (AI responses)
  - Amber/gold (shell commands, edits)
  - Teal/cyan (UI chrome)
  - Muted grays (dim text)

Dark background, easy on the eyes, no garish neons.
"""

from textual.theme import Theme

# ---------------------------------------------------------------------------
# Custom theme — matches the original Code Puppy CLI feel
# ---------------------------------------------------------------------------

CODE_PUPPY_THEME = Theme(
    name="code-puppy",
    primary="#5f87af",       # Steel blue — panels, borders, primary UI
    secondary="#875faf",     # Amethyst — AI responses, secondary accents
    accent="#af875f",        # Warm amber — highlights, selections
    warning="#d7af5f",       # Gold — warnings, token rate
    error="#af5f5f",         # Muted red — errors (not screaming)
    success="#5faf5f",       # Soft green — success, agent name
    foreground="#c0c0c0",    # Light gray — main text (not pure white)
    background="#1c1c1c",    # Near-black — like a terminal
    surface="#262626",       # Dark gray — panels, elevated surfaces
    panel="#303030",         # Slightly lighter — cards, overlays
    dark=True,
    luminosity_spread=0.15,
    text_alpha=0.9,
)

# ---------------------------------------------------------------------------
# Shared CSS variables and component styles
# ---------------------------------------------------------------------------

APP_CSS = """
/* ============================================
   Code Puppy TUI Theme
   ============================================ */

/* Screen backgrounds */
Screen {
    background: $surface;
}

/* Split panel defaults */
SplitPanel {
    height: 1fr;
}

SplitPanel > .split-panel--left {
    width: 35%;
    min-width: 25;
    border-right: solid $primary-darken-1;
}

SplitPanel > .split-panel--right {
    width: 1fr;
    padding: 1 2;
}

/* Searchable list */
SearchableList {
    height: 1fr;
}

SearchableList > Input {
    dock: top;
    margin: 0 1;
    height: 3;
}

SearchableList > ListView {
    height: 1fr;
}

/* List items */
.list-item {
    padding: 0 1;
    height: 1;
}

.list-item.--selected {
    background: $accent;
    color: $text;
    text-style: bold;
}

.list-item.--active {
    color: $success;
}

.list-item.--disabled {
    color: $text-muted;
    text-style: italic;
}

/* Navigation hints at bottom of panels */
.nav-hints {
    dock: bottom;
    height: auto;
    padding: 1;
    color: $text-muted;
    background: $surface;
    border-top: solid $primary-darken-1;
}

/* Preview panel content */
.preview-title {
    text-style: bold;
    color: $secondary;
    padding-bottom: 1;
}

.preview-label {
    text-style: bold;
    padding-right: 1;
}

.preview-value {
    color: $accent;
}

.preview-dim {
    color: $text-muted;
}
"""


def get_banner_css() -> str:
    """Generate CSS classes for banner colors from current config.

    Reads the banner color configuration and generates CSS classes
    that match the existing Rich color names used throughout the app.
    """
    try:
        from code_puppy.config import get_all_banner_colors

        colors = get_all_banner_colors()
    except Exception:
        colors = {}

    css_lines = ["/* Banner color classes (from config) */"]
    for name, color in colors.items():
        safe_name = name.replace("_", "-")
        css_lines.append(
            f".banner-{safe_name} {{ background: {color}; color: white; text-style: bold; padding: 0 1; }}"
        )

    return "\n".join(css_lines)
