"""Base agent class — a thin conductor delegating to focused helpers.

The real logic lives in sibling modules:
    * ``_history``     — token estimation, hashing, orphan pruning
    * ``_compaction``  — summarization/truncation + history processor factory
    * ``_builder``     — pydantic-ai agent construction + MCP wiring
    * ``_runtime``     — ``run_with_mcp`` orchestration, cancellation, retries
    * ``_key_listeners`` — Ctrl+X / cancel-agent keyboard listener threads

Keep this file under 300 lines. If it's growing, the new logic probably
belongs in one of the helpers above (or a new one).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pydantic_ai.models

from code_puppy.agents._builder import (
    build_pydantic_agent,
    build_tool_probe_for_agent,
    reload_mcp_servers,
)
from code_puppy.agents._compaction import summarize
from code_puppy.agents._history import (
    estimate_context_overhead,
    estimate_tokens_for_message,
    hash_message,
)
from code_puppy.agents._runtime import run_with_mcp, should_retry_streaming
from code_puppy.config import (
    get_agent_pinned_model,
    get_global_model_name,
    get_protected_token_count,
)
from code_puppy.model_factory import ModelFactory

# Backward-compat alias: existing tests import this name directly.
should_retry_streaming_exception = should_retry_streaming

__all__ = ["BaseAgent", "should_retry_streaming_exception"]


def _extract_pydantic_agent_tools(pyd_agent: Any) -> dict[str, Any] | None:
    """Return the registered tool dict for a pydantic-ai agent, or None.

    Handles the modern shape (``agent._function_toolset.tools``) and falls
    back to the legacy ``agent._tools`` attribute so older pydantic-ai
    versions still work. Returns ``None`` when neither is populated.
    """
    if pyd_agent is None:
        return None
    fts = getattr(pyd_agent, "_function_toolset", None)
    if fts is not None:
        tools = getattr(fts, "tools", None)
        if tools:
            return tools
    legacy = getattr(pyd_agent, "_tools", None)
    return legacy or None


class BaseAgent(ABC):
    """Abstract base for all Fast Puppy agents."""

    def __init__(self) -> None:
        self.id: str = str(uuid.uuid4())
        self._message_history: list[Any] = []
        self._compacted_message_hashes: set[int] = set()
        self._code_generation_agent: Any = None
        self._last_model_name: str | None = None
        self._runtime_model_name_override: str | None = None
        self._puppy_rules: str | None = None
        self._mcp_servers: list[Any] = []
        self.cur_model: pydantic_ai.models.Model | None = None
        self.pydantic_agent: Any = None
        # Cached probe agent used to count tool overhead before the real
        # pydantic agent has been built. Keyed implicitly by ``_last_model_name``
        # so model swaps invalidate it via ``_probe_model_name``.
        self._tool_probe_agent: Any = None
        self._probe_model_name: str | None = None
        # Memo for the resolved context-window length, keyed by model name so a
        # model switch recomputes it. Avoids re-reading model config on every
        # per-request history-processor cycle.
        self._ctx_len_cache: tuple[str | None, int] | None = None
        # Memo for the context-overhead estimate, keyed by
        # ``(model_name, hash(resolved_system_prompt))`` so a model switch or a
        # changed system prompt recomputes it. The history processor invokes
        # ``_estimate_context_overhead`` on every model request; without this we
        # re-resolve the system prompt + re-run prepare_prompt_for_model each
        # time. Stored as ``(key, value)``; recompute only when the key changes.
        self._ctx_overhead_cache: tuple[tuple[str | None, int], int] | None = None
        # Memo for the fully-assembled system prompt (base + load_prompt plugin
        # fragments + identity), keyed by ``(model_name, callbacks generation)``.
        # ``_estimate_context_overhead`` runs on every model request and would
        # otherwise re-run every load_prompt plugin (memory recall, skills, ...)
        # each time just to rebuild a near-constant string. See
        # ``_full_system_prompt_for_overhead``.
        self._full_prompt_cache: tuple[tuple[str | None, int], str] | None = None

    # ---- Abstract interface ------------------------------------------------
    @property
    @abstractmethod
    def name(self) -> str:
        """Stable machine identifier (e.g. ``python-programmer``)."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in UIs."""

    @property
    @abstractmethod
    def description(self) -> str:
        """One-line summary of what this agent does."""

    @abstractmethod
    def get_system_prompt(self) -> str:
        """Return the agent's system prompt (identity is appended separately)."""

    @abstractmethod
    def get_available_tools(self) -> list[str]:
        """Return the list of tool names this agent should register."""

    # ---- Optional overrides ------------------------------------------------
    def get_tools_config(self) -> dict[str, Any] | None:
        return None

    def get_user_prompt(self) -> str | None:
        return None

    def get_runtime_model_name_override(self) -> str | None:
        """Return a temporary per-run model override, if one is active."""
        return self._runtime_model_name_override

    def set_runtime_model_name_override(self, model_name: str | None) -> None:
        """Set a temporary per-run model override.

        This is intentionally not persisted. It lets orchestration code run an
        agent on a specific model for one invocation without mutating global,
        pinned, or JSON agent model configuration.
        """
        self._runtime_model_name_override = model_name

    @contextmanager
    def temporary_model_name_override(self, model_name: str | None) -> Iterator[None]:
        """Temporarily apply a per-run model override within a scoped block."""
        previous_model_name = self.get_runtime_model_name_override()
        try:
            self.set_runtime_model_name_override(model_name)
            yield
        finally:
            self.set_runtime_model_name_override(previous_model_name)

    def get_model_name(self) -> str | None:
        override = self.get_runtime_model_name_override()
        if override:
            return override
        pinned = get_agent_pinned_model(self.name)
        return pinned if pinned else get_global_model_name()

    # ---- Identity ---------------------------------------------------------
    def get_identity(self) -> str:
        return f"{self.name}-{self.id[:6]}"

    def get_identity_prompt(self) -> str:
        return (
            f"\n\nYour ID is `{self.get_identity()}`. "
            "Use this for any tasks which require identifying yourself "
            "such as claiming task ownership or coordination with other agents."
        )

    def get_full_system_prompt(self) -> str:
        """Assemble the runtime system prompt.

        Layered as: authored prompt (``get_system_prompt``) + per-turn
        ``load_prompt`` plugin fragments + this instance's identity.

        The ``load_prompt`` fragments (live timestamp/CWD, file-permission
        rules, kennel memory, ...) and the identity ID are *runtime* concerns.
        They live here — not in ``get_system_prompt`` — so they're recomputed
        fresh every run and never get persisted into static agent definitions
        (e.g. when an agent is cloned to JSON). See ``clone_agent``.
        """
        from code_puppy import callbacks

        prompt = self.get_system_prompt()
        prompt_additions = callbacks.on_load_prompt()
        if prompt_additions:
            prompt += "\n" + "\n".join(prompt_additions)
        return prompt + self.get_identity_prompt()

    def _full_system_prompt_for_overhead(self) -> str:
        """``get_full_system_prompt`` memoized for context-overhead accounting.

        ``_estimate_context_overhead`` runs on every model request; calling
        ``get_full_system_prompt`` there re-runs every ``load_prompt`` plugin
        (memory recall, skills, file-permission rules, ...) just to rebuild a
        string that almost never changes mid-run. We cache it keyed on
        ``(model_name, callbacks.get_load_prompt_generation())`` so the plugins
        only re-run when the model switches or the callback registry changes.

        This memo feeds the context-usage ESTIMATE only — the real prompt sent
        to the model is assembled fresh at agent-build time — so a briefly stale
        value (e.g. after a plugin changes the *content* it returns without a
        registry change) is harmless to correctness; it only nudges compaction
        timing and the ``/context`` badge.
        """
        from code_puppy import callbacks

        key = (self.get_model_name(), callbacks.get_load_prompt_generation())
        cached = self._full_prompt_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        prompt = self.get_full_system_prompt()
        self._full_prompt_cache = (key, prompt)
        return prompt

    # ---- Message history (plain dict-level access) ------------------------
    def get_message_history(self) -> list[Any]:
        return self._message_history

    def set_message_history(self, history: list[Any]) -> None:
        self._message_history = history

    def clear_message_history(self) -> None:
        self._message_history = []
        self._compacted_message_hashes.clear()

    def append_to_message_history(self, message: Any) -> None:
        self._message_history.append(message)

    # ---- Token / context helpers ------------------------------------------
    def estimate_tokens_for_message(self, message: Any) -> int:
        return estimate_tokens_for_message(message, self.get_model_name())

    def hash_message(self, message: Any) -> int:
        return hash_message(message)

    def _get_model_context_length(self) -> int:
        """Context window for the agent's effective model (fallback: 128k)."""
        model_name = self.get_model_name()
        cached = self._ctx_len_cache
        if cached is not None and cached[0] == model_name:
            return cached[1]
        try:
            configs = ModelFactory.load_config()
            cfg = configs.get(model_name, {})
            length = int(cfg.get("context_length", 128000))
        except Exception:
            length = 128000
        self._ctx_len_cache = (model_name, length)
        return length

    def _estimate_context_overhead(self) -> int:
        """Tokens used by system prompt + registered pydantic tools.

        Memoized on ``(model_name, sha1(system_prompt))``: the history
        processor calls this on every model request, and re-resolving the
        system prompt + re-running ``prepare_prompt_for_model`` each time is
        wasteful when neither the model nor the prompt has changed. Mirrors the
        ``_ctx_len_cache`` pattern — recompute only when the key changes. A
        strong digest is used instead of ``hash()`` so two distinct prompts
        that happen to collide under ``str.__hash__`` can't serve a stale
        overhead (which would skew proportion_used / compaction timing).
        """
        import hashlib

        model_name = self.get_model_name()
        system_prompt = self._full_system_prompt_for_overhead()
        key = (
            model_name,
            hashlib.sha1(system_prompt.encode("utf-8", "replace")).hexdigest(),
        )
        cached = self._ctx_overhead_cache
        if cached is not None and cached[0] == key:
            return cached[1]

        try:
            from code_puppy.model_utils import prepare_prompt_for_model

            prepared = prepare_prompt_for_model(
                model_name=model_name or "",
                system_prompt=system_prompt,
                user_prompt="",
                prepend_system_to_user=False,
            )
            resolved = prepared.instructions or system_prompt
        except Exception:
            resolved = system_prompt

        tools_source = self.pydantic_agent or self._get_tool_probe()
        tools = _extract_pydantic_agent_tools(tools_source) if tools_source else None
        mcp_servers = getattr(self, "_mcp_servers", None) or None
        overhead = estimate_context_overhead(
            resolved,
            tools,
            model_name,
            mcp_servers=mcp_servers,
        )
        self._ctx_overhead_cache = (key, overhead)
        return overhead

    def _get_tool_probe(self) -> Any:
        """Lazily build (and cache) a tool-probe pydantic agent.

        Used so context-window estimators can count tool docs/schemas even on a
        fresh session, before the real pydantic agent has been constructed.
        The probe is invalidated whenever the agent's effective model name
        changes.
        """
        current_model = self.get_model_name()
        if (
            self._tool_probe_agent is not None
            and self._probe_model_name == current_model
        ):
            return self._tool_probe_agent
        probe = build_tool_probe_for_agent(self)
        if probe is not None:
            self._tool_probe_agent = probe
            self._probe_model_name = current_model
        return probe

    # ---- Orchestration (thin delegations) ---------------------------------
    def summarize_messages(
        self,
        messages: list[Any],
        with_protection: bool = True,
    ) -> tuple[list, list]:
        """Delegate to ``_compaction.summarize`` with config-derived protection."""
        return summarize(
            messages,
            get_protected_token_count(),
            with_protection=with_protection,
            model_name=self.get_model_name(),
        )

    def reload_code_generation_agent(self, message_group: str | None = None) -> Any:
        return build_pydantic_agent(self, output_type=str, message_group=message_group)

    async def run_with_mcp(self, prompt: str, **kwargs: Any) -> Any:
        return await run_with_mcp(self, prompt, **kwargs)

    # ---- MCP integration shims --------------------------------------------
    def update_mcp_tool_cache_sync(self) -> None:
        """Best-effort warm of each MCP server's ``_cached_tools``.

        Pydantic-ai caches MCP tool defs on each server after the first
        ``list_tools()`` call. We piggy-back on that cache for context-window
        overhead estimates (see ``_history._estimate_mcp_tool_tokens``).

        Without this warm-up the cache stays empty until the first agent run,
        so the ``/context`` badge under-reports MCP overhead right after
        ``/mcp start``. Here we schedule ``list_tools()`` for any server that
        looks running, but we never block and we swallow all errors — the
        cache will eventually be populated by the agent run itself.
        """
        import asyncio

        servers = getattr(self, "_mcp_servers", None) or []
        if not servers:
            return None

        # Only warm the cache when already inside a running loop. Using
        # get_running_loop() (instead of the deprecated get_event_loop())
        # raises RuntimeError when no loop is running, which is exactly the
        # "nothing to warm" case.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None
        if not loop.is_running():
            return None

        async def _warm(server: Any) -> None:
            try:
                if getattr(server, "_cached_tools", None):
                    return
                if not getattr(server, "is_running", False):
                    return
                await server.list_tools()
            except Exception:
                # Cache stays empty; estimator handles that gracefully.
                return

        for server in servers:
            try:
                loop.create_task(_warm(server))
            except Exception:
                continue
        return None

    def reload_mcp_servers(self) -> list[Any]:
        return reload_mcp_servers(agent_name=self.name)
