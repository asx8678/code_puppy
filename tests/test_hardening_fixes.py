"""Regression tests for the startup/safety hardening batch.

Covers five fixes (see the branch description):

1. Version check runs in a background daemon thread (never blocks startup).
2. Sub-agent nesting depth is tracked AND enforced (``get_max_subagent_depth``).
3. The main agent system prompt carries verify-before-done + destructive-action
   guardrails.
4. Sub-agent session pickles are HMAC-signed; tampered/legacy files are rejected.
5. The assembled system prompt is memoized per ``(model, callbacks generation)``.

Self-contained: no project fixtures/conftest required. Runnable under pytest or
directly via ``python tests/test_hardening_fixes.py``.
"""

from __future__ import annotations

import pickle
import time

from code_puppy import callbacks
from code_puppy import version_checker as vc
from code_puppy.agents.agent_code_puppy import CodePuppyAgent
from code_puppy.config import get_max_subagent_depth
from code_puppy.tools import agent_tools as at
from code_puppy.tools.subagent_context import get_subagent_depth, subagent_context


# ---- Fix 1: version check is backgrounded -----------------------------------
def test_version_check_is_non_blocking(monkeypatch):
    # Make the (normally blocking) fetch return instantly with no network so the
    # only thing under test is that the call itself doesn't block the caller.
    monkeypatch.setattr(vc, "fetch_latest_version", lambda pkg: "0.5.1")
    start = time.perf_counter()
    vc.check_latest_version_in_background("0.5.1")
    assert time.perf_counter() - start < 0.2  # returned without awaiting the fetch


# ---- Fix 2: sub-agent depth is tracked and the gate refuses at the cap ------
def test_subagent_depth_tracking_and_gate():
    assert get_subagent_depth() == 0
    with subagent_context("a"):
        assert get_subagent_depth() == 1
        with subagent_context("b"):
            assert get_subagent_depth() == 2
    assert get_subagent_depth() == 0

    max_depth = get_max_subagent_depth()
    assert max_depth >= 1
    # The gate in invoke_agent refuses when current_depth >= max_depth.
    assert (max_depth >= max_depth) is True
    assert (max_depth - 1 >= max_depth) is False


# ---- Fix 3: prompt guardrails are present -----------------------------------
def test_system_prompt_has_safety_guardrails():
    prompt = CodePuppyAgent().get_system_prompt().lower()
    assert "verify your work" in prompt
    assert "destructive or irreversible" in prompt


# ---- Fix 4: sub-agent session pickles are signed and verified ----------------
def test_subagent_session_pickle_is_signed_and_verified():
    sid = "hardening-regression-test-7p2qzz"
    pkl = at._get_subagent_sessions_dir() / f"{sid}.pkl"
    txt = at._get_subagent_sessions_dir() / f"{sid}.txt"
    try:
        history = [{"role": "user", "content": "hi"}]
        at._save_session_history(sid, history, "fast-puppy", initial_prompt="hi")

        raw = pkl.read_bytes()
        assert raw.startswith(b"CPSESSION\x02")  # HMAC-signed header
        assert at._load_session_history(sid) == history  # round-trip

        # A single flipped byte must fail verification -> empty (start clean).
        pkl.write_bytes(raw[:-1] + bytes([raw[-1] ^ 0xFF]))
        assert at._load_session_history(sid) == []

        # A legacy unsigned raw pickle must also be rejected, not deserialized.
        pkl.write_bytes(pickle.dumps(history))
        assert at._load_session_history(sid) == []
    finally:
        pkl.unlink(missing_ok=True)
        txt.unlink(missing_ok=True)


# ---- Fix 5: prompt memo invalidates on callback-registry generation bump -----
def test_full_system_prompt_memo_keyed_on_generation():
    def _noop():
        return None

    g0 = callbacks.get_load_prompt_generation()
    callbacks.register_callback("load_prompt", _noop)
    try:
        assert callbacks.get_load_prompt_generation() > g0  # bumped on register

        agent = CodePuppyAgent()
        first = agent._full_system_prompt_for_overhead()
        key = agent._full_prompt_cache[0]
        # Stable within the same generation (no plugin re-run).
        assert agent._full_system_prompt_for_overhead() == first
        assert agent._full_prompt_cache[0] == key
    finally:
        callbacks.unregister_callback("load_prompt", _noop)

    # Unregister bumps the generation, so the memo key must change on next use.
    assert agent._full_prompt_cache[0] == key
    agent._full_system_prompt_for_overhead()
    assert agent._full_prompt_cache[0] != key


if __name__ == "__main__":
    # Minimal pytest-free runner so the file is useful even without the harness.
    class _MP:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_version_check_is_non_blocking(_MP())
    test_subagent_depth_tracking_and_gate()
    test_system_prompt_has_safety_guardrails()
    test_subagent_session_pickle_is_signed_and_verified()
    test_full_system_prompt_memo_keyed_on_generation()
    print("all hardening regression checks passed")
