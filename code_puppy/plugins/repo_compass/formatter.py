from __future__ import annotations

from pathlib import Path

from .turbo_indexer_bridge import FileSummary


def _detect_project_name(root: Path) -> str:
    return root.name or "project"


def format_structure_map(
    root: Path, summaries: list[FileSummary], max_chars: int = 2400
) -> str | None:
    if not summaries:
        return None

    lines = [
        "## Repo Compass",
        f"Project: {_detect_project_name(root)}",
        "Structural context map:",
    ]

    for summary in summaries:
        bullet = f"- {summary.path} [{summary.kind}]"
        if summary.symbols:
            bullet += f": {'; '.join(summary.symbols)}"
        lines.append(bullet)

    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text

    trimmed: list[str] = lines[:3]
    for line in lines[3:]:
        if len("\n".join(trimmed + [line, "- ... truncated ..."])) > max_chars:
            trimmed.append("- ... truncated ...")
            break
        trimmed.append(line)
    return "\n".join(trimmed)
