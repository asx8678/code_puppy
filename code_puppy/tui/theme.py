"""Textual CSS theme for Code Puppy TUI.

Maps existing banner colors from code_puppy.config to CSS variables,
and defines the consistent color palette used across all screens.
"""

# Standard CSS that all screens share
# Uses Textual's CSS variable system for theming
APP_CSS = """
/* ============================================
   Code Puppy TUI Theme
   ============================================ */

/* Base colors */
$puppy-cyan: rgb(0, 200, 200);
$puppy-green: rgb(0, 200, 100);
$puppy-yellow: rgb(200, 180, 0);
$puppy-red: rgb(200, 60, 60);
$puppy-blue: rgb(60, 120, 200);
$puppy-purple: rgb(140, 80, 200);
$puppy-dim: rgb(120, 120, 120);

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
    border-right: solid $primary-lighten-2;
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
    border-top: solid $primary-lighten-3;
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
