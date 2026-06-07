"""Pre-rendered "FAST PUPPY" startup banner.

This is the ``ansi_shadow`` figlet rendering of "FAST PUPPY", captured verbatim
so we don't pull in the ``pyfiglet`` dependency just to draw a static banner.
The gradient (blue → cyan → green, top to bottom) is applied with Rich markup.
"""

from __future__ import annotations

# 'ansi_shadow' figlet of "FAST PUPPY" (captured from pyfiglet).
FAST_PUPPY_ASCII = (
    "███████╗ █████╗ ███████╗████████╗    ██████╗ ██╗   ██╗██████╗ ██████╗ ██╗   ██╗\n"
    "██╔════╝██╔══██╗██╔════╝╚══██╔══╝    ██╔══██╗██║   ██║██╔══██╗██╔══██╗╚██╗ ██╔╝\n"
    "█████╗  ███████║███████╗   ██║       ██████╔╝██║   ██║██████╔╝██████╔╝ ╚████╔╝ \n"
    "██╔══╝  ██╔══██║╚════██║   ██║       ██╔═══╝ ██║   ██║██╔═══╝ ██╔═══╝   ╚██╔╝  \n"
    "██║     ██║  ██║███████║   ██║       ██║     ╚██████╔╝██║     ██║        ██║   \n"
    "╚═╝     ╚═╝  ╚═╝╚══════╝   ╚═╝       ╚═╝      ╚═════╝ ╚═╝     ╚═╝        ╚═╝   "
)

_GRADIENT = ("bright_blue", "bright_cyan", "bright_green")


def gradient_banner_lines() -> list[str]:
    """Return the banner as Rich-markup lines, blue→cyan→green top to bottom."""
    lines: list[str] = []
    for i, line in enumerate(FAST_PUPPY_ASCII.split("\n")):
        if line.strip():
            color = _GRADIENT[min(i // 2, len(_GRADIENT) - 1)]
            lines.append(f"[{color}]{line}[/{color}]")
        else:
            lines.append("")
    return lines


def gradient_banner() -> str:
    """Return the gradient FAST PUPPY banner as a single string."""
    return "\n".join(gradient_banner_lines())
