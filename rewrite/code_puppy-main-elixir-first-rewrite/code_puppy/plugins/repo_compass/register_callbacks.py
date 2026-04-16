import logging
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback

from .config import load_config
from .decision_markers import scan_decision_markers
from .formatter import format_structure_map
from .tech_stack import detect_build_commands, detect_tech_stack
from .turbo_indexer_bridge import build_structure_map, get_indexer_status

logger = logging.getLogger(__name__)


def _log_indexer_status():
    """Log which indexer backend is active at startup."""
    status = get_indexer_status()
    # bd-83: Report actual backend (elixir/python), not stale "turbo_ops"
    backend = status.get("backend", "python")
    if status.get("rust_available") or backend == "elixir":
        logger.debug(f"Repo Compass using native backend ({backend})")
    else:
        logger.debug("Repo Compass using Python backend")


def _format_tech_stack_line(root: Path) -> str | None:
    """Format tech stack as a single line (≈15 tokens)."""
    try:
        stack = detect_tech_stack(root)
        if not stack:
            return None

        # Take top 5-8 items, formatted compactly
        top_items = stack[:8]
        parts = []
        for item in top_items:
            if item.version:
                parts.append(f"{item.name} {item.version}")
            else:
                parts.append(item.name)

        if parts:
            return f"Tech stack: {', '.join(parts)}"
        return None
    except Exception as exc:
        logger.debug("Tech stack detection failed: %s", exc)
        return None


def _format_build_commands_line(root: Path) -> str | None:
    """Format build commands as a single line (≈10 tokens)."""
    try:
        commands = detect_build_commands(root)
        if not commands:
            return None

        # Format key commands
        parts = []
        for key in ["test", "lint", "dev", "build", "format", "typecheck"]:
            if key in commands:
                parts.append(f"{key}={commands[key]}")

        if parts:
            return f"Build commands: {', '.join(parts)}"
        return None
    except Exception as exc:
        logger.debug("Build command detection failed: %s", exc)
        return None


def _format_decision_markers_section(root: Path, max_markers: int = 3) -> str | None:
    """Format decision markers as a compact section (≈30-50 tokens)."""
    try:
        markers = scan_decision_markers(root, max_files=20, max_markers=max_markers)
        if not markers:
            return None

        lines = ["Key decisions:"]
        for m in markers:
            # Compact single-line format: "path:LINENO [TYPE] snippet"
            snippet = m.text[:50] + "..." if len(m.text) > 50 else m.text
            lines.append(f"  {m.path}:{m.line_number} [{m.marker_type}] {snippet}")

        return "\n".join(lines)
    except Exception as exc:
        logger.debug("Decision marker scanning failed: %s", exc)
        return None


def _build_repo_context(root: Path | None = None) -> str | None:
    cfg = load_config()
    if not cfg.enabled:
        return None

    project_root = root or Path.cwd()
    try:
        summaries = build_structure_map(
            project_root,
            max_files=cfg.max_files,
            max_symbols_per_file=cfg.max_symbols_per_file,
        )
        structure_text = format_structure_map(
            project_root, summaries, max_chars=cfg.max_prompt_chars
        )

        if structure_text is None:
            return None

        # Build additional context sections
        context_parts = [structure_text]

        # Tech stack (≈15 tokens)
        tech_line = _format_tech_stack_line(project_root)
        if tech_line:
            context_parts.append(tech_line)

        # Build commands (≈10 tokens)
        build_line = _format_build_commands_line(project_root)
        if build_line:
            context_parts.append(build_line)

        # Decision markers (≈30-50 tokens)
        decisions_section = _format_decision_markers_section(
            project_root, max_markers=3
        )
        if decisions_section:
            context_parts.append(decisions_section)

        return "\n\n".join(context_parts)
    except Exception as exc:  # fail gracefully per plugin rules
        logger.debug("Repo Compass failed to build context: %s", exc)
        return None


def _inject_repo_context(
    model_name: str, default_system_prompt: str, user_prompt: str
) -> dict[str, Any] | None:
    context = _build_repo_context()
    if not context:
        return None

    enhanced_prompt = f"{default_system_prompt}\n\n{context}"
    return {
        "instructions": enhanced_prompt,
        "user_prompt": user_prompt,
        "handled": False,
    }


register_callback("get_model_system_prompt", _inject_repo_context)
register_callback("startup", _log_indexer_status)
