"""Smart model routing for simple tasks.

Analyzes prompt complexity and routes simple queries to a cheaper
"simple_model" while reserving the default (expensive) model for complex
tasks.

Configuration keys in ``puppy.cfg``::

    [puppy]
    routing_enabled = true
    simple_model = gpt-4o-mini
    complexity_threshold = 0.5

Hook points
-----------
* ``startup``          – patch ``BaseAgent.run_with_mcp`` to intercept prompts
* ``custom_command``   – ``/model_router`` status / toggle
* ``custom_command_help`` – help entry
"""

from __future__ import annotations

import logging
import re
from functools import wraps
from typing import Any

from code_puppy.callbacks import register_callback

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_CONFIG_KEYS = {
    "routing_enabled": True,
    "simple_model": "gpt-4o-mini",
    "complexity_threshold": 0.5,
}


def _load_config() -> dict[str, Any]:
    """Read routing configuration from ``puppy.cfg``."""
    from code_puppy.config import get_value, _is_truthy

    cfg: dict[str, Any] = {}
    raw_enabled = get_value("routing_enabled")
    cfg["routing_enabled"] = (
        _is_truthy(raw_enabled, default=True) if raw_enabled is not None else True
    )
    cfg["simple_model"] = get_value("simple_model") or _CONFIG_KEYS["simple_model"]
    raw_threshold = get_value("complexity_threshold")
    try:
        cfg["complexity_threshold"] = (
            float(raw_threshold) if raw_threshold is not None else 0.5
        )
    except (ValueError, TypeError):
        cfg["complexity_threshold"] = 0.5
    return cfg


# ---------------------------------------------------------------------------
# Complexity analysis
# ---------------------------------------------------------------------------

# Keywords / phrases that signal a complex task.
_COMPLEXITY_KEYWORDS: list[str] = [
    "refactor",
    "refactoring",
    "analyze",
    "analysis",
    "debug",
    "debugging",
    "test",
    "tests",
    "testing",
    "unittest",
    "pytest",
    "implement",
    "implementation",
    "architecture",
    "design pattern",
    "multi-file",
    "across files",
    "all files",
    "each file",
    "every file",
    "optimization",
    "optimize",
    "performance",
    "security",
    "vulnerability",
    "migrate",
    "migration",
    "deploy",
    "deployment",
    "integration",
    "comprehensive",
    "thorough",
    "detailed",
    "in-depth",
    "deep dive",
    "complex",
    "complicated",
    "intricate",
    "sophisticated",
]

# Patterns that suggest the prompt will exercise tools.
_TOOL_PATTERNS: list[str] = [
    r"\blist_files\b",
    r"\bread_file\b",
    r"\bcreate_file\b",
    r"\breplace_in_file\b",
    r"\bgrep\b",
    r"\bshell\b",
    r"\bcommand\b",
    r"\bls\b",
    r"\bcat\b",
    r"\bgit\b",
    r"\bfind\b",
    r"\btool\b",
    r"\bfunction\b",
    r"\bclass\b",
    r"\bmodule\b",
    r"\bpackage\b",
    r"\bfile\b",
    r"\bdirectory\b",
    r"\bfolder\b",
    r"\bsrc\b",
]


def calculate_complexity(prompt: str) -> tuple[float, str]:
    """Return a ``(score, reason)`` tuple for *prompt*.

    ``score`` is in ``[0.0, 1.0]`` – higher means more complex.

    Scoring weights:
    * prompt length   30 %
    * keywords        50 %
    * tool indicators 20 %
    """
    if not prompt or not prompt.strip():
        return 0.0, "empty prompt"

    prompt_lower = prompt.lower()

    # --- length score (0-1) ---------------------------------------------------
    length = len(prompt)
    if length < 50:
        length_score = 0.1
    elif length < 150:
        length_score = 0.3
    elif length < 400:
        length_score = 0.5
    elif length < 800:
        length_score = 0.7
    else:
        length_score = 1.0

    # --- keyword score (0-1) --------------------------------------------------
    matched_keywords = [
        kw for kw in _COMPLEXITY_KEYWORDS
        if re.search(r'\b' + re.escape(kw) + r'\b', prompt_lower)
    ]
    keyword_score = min(len(matched_keywords) / 4.0, 1.0)

    # --- tool score (0-1) -----------------------------------------------------
    tool_matches = sum(
        1 for p in _TOOL_PATTERNS if re.search(p, prompt_lower)
    )
    tool_score = min(tool_matches / 4.0, 1.0)

    # --- combined score -------------------------------------------------------
    score = length_score * 0.3 + keyword_score * 0.5 + tool_score * 0.2
    score = round(min(max(score, 0.0), 1.0), 4)

    # Build human-readable reason
    parts: list[str] = []
    parts.append(f"len={length}")
    if matched_keywords:
        parts.append(f"kw=[{', '.join(matched_keywords[:5])}]")
    if tool_matches:
        parts.append(f"tools={tool_matches}")
    reason = "; ".join(parts)

    return score, reason


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------

def select_model(prompt: str, config: dict[str, Any]) -> tuple[str, float, str]:
    """Choose the best model for *prompt* given *config*.

    Returns ``(model_name, complexity_score, reason)``.
    """
    from code_puppy.config import get_global_model_name

    score, reason = calculate_complexity(prompt)
    threshold = config["complexity_threshold"]

    if score < threshold:
        return config["simple_model"], score, reason
    return get_global_model_name(), score, reason


# ---------------------------------------------------------------------------
# Run-with-mcp wrapper (startup patch)
# ---------------------------------------------------------------------------

_original_run_with_mcp = None  # set once during _on_startup


def _make_run_with_mcp_wrapper(original_fn):
    """Return an async wrapper that routes before delegating to *original_fn*."""

    @wraps(original_fn)
    async def _wrapped_run_with_mcp(self, prompt: str, *args: Any, **kwargs: Any):
        config = _load_config()

        if config["routing_enabled"] and prompt:
            target_model, score, reason = select_model(prompt, config)

            try:
                from code_puppy.config import get_global_model_name, set_model_name

                current_model = get_global_model_name()
            except Exception:
                current_model = None

            if target_model and target_model != current_model:
                logger.info(
                    "🔀 Model routing: %s → %s  (score=%.3f, %s)",
                    current_model,
                    target_model,
                    score,
                    reason,
                )
                set_model_name(target_model)
                # Force agent reload so the new model takes effect this turn
                try:
                    self.reload_code_generation_agent()
                except Exception:
                    logger.debug("agent reload after model switch failed", exc_info=True)

        return await original_fn(self, prompt, *args, **kwargs)

    return _wrapped_run_with_mcp


# ---------------------------------------------------------------------------
# Startup hook
# ---------------------------------------------------------------------------

def _on_startup() -> None:
    """Patch ``BaseAgent.run_with_mcp`` once at application start."""
    global _original_run_with_mcp

    from code_puppy.agents.base_agent import BaseAgent

    if _original_run_with_mcp is not None:
        return  # already patched

    _original_run_with_mcp = BaseAgent.run_with_mcp
    BaseAgent.run_with_mcp = _make_run_with_mcp_wrapper(_original_run_with_mcp)

    config = _load_config()
    if config["routing_enabled"]:
        logger.info(
            "🔀 Model router active — simple_model=%s  threshold=%.2f",
            config["simple_model"],
            config["complexity_threshold"],
        )
    else:
        logger.debug("Model router loaded but routing is disabled")


# ---------------------------------------------------------------------------
# Custom command  —  /model_router
# ---------------------------------------------------------------------------

def _custom_help() -> list[tuple[str, str]]:
    return [
        ("model_router", "Show / toggle smart model routing for simple tasks"),
    ]


def _handle_command(command: str, name: str) -> bool | None:
    if name != "model_router":
        return None

    from code_puppy.messaging import emit_info, emit_warning
    from code_puppy.config import get_global_model_name, set_config_value

    parts = command.strip().split()
    sub = parts[1] if len(parts) > 1 else "status"

    config = _load_config()

    if sub == "status":
        status_emoji = "✅" if config["routing_enabled"] else "❌"
        emit_info(
            f"🔀 Model Router Status:\n"
            f"   Enabled:        {status_emoji} {config['routing_enabled']}\n"
            f"   Simple model:   {config['simple_model']}\n"
            f"   Threshold:      {config['complexity_threshold']:.2f}\n"
            f"   Current model:  {get_global_model_name()}"
        )
        return True

    if sub == "enable":
        set_config_value("routing_enabled", "true")
        emit_info("🔀 Model routing ENABLED")
        return True

    if sub == "disable":
        set_config_value("routing_enabled", "false")
        emit_info("🔀 Model routing DISABLED")
        return True

    if sub == "threshold" and len(parts) >= 3:
        try:
            val = float(parts[2])
            if 0.0 <= val <= 1.0:
                set_config_value("complexity_threshold", str(val))
                emit_info(f"🔀 Complexity threshold set to {val:.2f}")
            else:
                emit_warning("Threshold must be between 0.0 and 1.0")
        except ValueError:
            emit_warning("Invalid threshold value — must be a number")
        return True

    if sub == "simple-model" and len(parts) >= 3:
        model = " ".join(parts[2:])
        set_config_value("simple_model", model)
        emit_info(f"🔀 Simple model set to '{model}'")
        return True

    emit_info(
        "Usage: /model_router [status|enable|disable|threshold <val>|simple-model <name>]"
    )
    return True


# ---------------------------------------------------------------------------
# Register everything
# ---------------------------------------------------------------------------

register_callback("startup", _on_startup)
register_callback("custom_command_help", _custom_help)
register_callback("custom_command", _handle_command)
