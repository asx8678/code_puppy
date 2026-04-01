"""Textual CSS theme for Code Puppy TUI.

Color palette matches the original Code Puppy CLI exactly:
  - Deep blue primary (deep_sky_blue4)
  - Purple secondary (medium_purple4 / dark_violet)
  - Cyan/teal accents (dark_cyan / dark_slate_gray3)
  - Green success (sea_green3)
  - Pink errors (deep_pink4)
  - Black background, just like a terminal
"""

from textual.theme import Theme

# ---------------------------------------------------------------------------
# Custom theme — exact match to the original Code Puppy CLI colors
# ---------------------------------------------------------------------------

CODE_PUPPY_THEME = Theme(
    name="code-puppy",
    primary="#005faf",       # deep_sky_blue4 — the main CLI color
    secondary="#5f5f87",     # medium_purple4 — AI responses
    accent="#00af87",        # dark_cyan — tools, highlights
    warning="#d7af00",       # yellow — warnings (not brown)
    error="#af005f",         # deep_pink4 — errors
    success="#5fd787",       # sea_green3 — success, confirmations
    foreground="#bcbcbc",    # grey74 — readable but not blinding
    background="#000000",    # pure black — like the old terminal
    surface="#121212",       # grey7 — barely lifted from black
    panel="#1c1c1c",         # grey11 — subtle panel elevation
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
    border-right: solid $primary;
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
    border-top: solid $primary;
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
