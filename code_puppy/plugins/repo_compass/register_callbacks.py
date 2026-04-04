from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from code_puppy.callbacks import register_callback

from .config import load_config
from .formatter import format_structure_map
from .indexer import build_structure_map

logger = logging.getLogger(__name__)


def _build_repo_context(root: Path | None = None, condensed: bool = False) -> str | None:
    cfg = load_config()
    if not cfg.enabled:
        return None

    project_root = root or Path.cwd()
    try:
        if condensed:
            max_files = cfg.condensed_max_files
            max_symbols_per_file = cfg.condensed_max_symbols_per_file
            max_chars = cfg.condensed_max_prompt_chars
        else:
            max_files = cfg.max_files
            max_symbols_per_file = cfg.max_symbols_per_file
            max_chars = cfg.max_prompt_chars
        
        summaries = build_structure_map(
            project_root,
            max_files=max_files,
            max_symbols_per_file=max_symbols_per_file,
        )
        return format_structure_map(project_root, summaries, max_chars=max_chars)
    except Exception as exc:  # fail gracefully per plugin rules
        logger.debug("Repo Compass failed to build context: %s", exc)
        return None


def _inject_repo_context(
    model_name: str, default_system_prompt: str, user_prompt: str
) -> dict[str, Any] | None:
    # Check budget tracker for condensed mode
    from code_puppy.system_prompt_budget import get_current_budget_tracker
    budget_tracker = get_current_budget_tracker()
    use_condensed = False
    if budget_tracker and budget_tracker.config.enabled:
        use_condensed = budget_tracker.should_use_condensed
    
    context = _build_repo_context(condensed=use_condensed)
    if not context:
        return None

    # Track contribution in budget tracker
    if budget_tracker and budget_tracker.config.enabled:
        budget_tracker.add_contribution("repo_compass", context, condensed=use_condensed)
    
    enhanced_prompt = f"{default_system_prompt}\n\n{context}"
    return {
        "instructions": enhanced_prompt,
        "user_prompt": user_prompt,
        "handled": False,
    }


register_callback("get_model_system_prompt", _inject_repo_context)
