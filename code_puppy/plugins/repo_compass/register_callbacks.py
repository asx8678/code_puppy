from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback

from .config import load_config
from .formatter import format_structure_map
from .turbo_indexer_bridge import build_structure_map, get_indexer_status

logger = logging.getLogger(__name__)


def _log_indexer_status():
    """Log which indexer backend is active at startup."""
    status = get_indexer_status()
    if status["rust_available"]:
        logger.debug("Repo Compass using Rust acceleration (turbo_ops)")
    else:
        logger.debug("Repo Compass using Python backend")


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
        return format_structure_map(
            project_root, summaries, max_chars=cfg.max_prompt_chars
        )
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
