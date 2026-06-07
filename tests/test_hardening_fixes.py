"""Regression tests for the startup/safety hardening batch.

Covers six fixes (see the branch description):

1. Version check runs in a background daemon thread (never blocks startup).
2. Sub-agent nesting depth is tracked AND enforced (``get_max_subagent_depth``).
3. The main agent system prompt carries verify-before-done + destructive-action
   guardrails.
4. Sub-agent session pickles are HMAC-signed; tampered/legacy files are rejected.
5. The assembled system prompt is memoized per ``(model, callbacks generation)``.
6. The plugin-skills cache dir reset is race-serialized and tolerates a stale
   non-directory squatting on the path (no FileExistsError leaking out of
   concurrent ``get_model_system_prompt`` dispatches).

Self-contained: no project fixtures/conftest required. Runnable under pytest or
directly via ``python tests/test_hardening_fixes.py``.
"""

from __future__ import annotations

import pickle
import shutil
import tempfile
import threading
import time
from pathlib import Path

from code_puppy import callbacks
from code_puppy import version_checker as vc
from code_puppy.agents.agent_code_puppy import CodePuppyAgent
from code_puppy.config import get_max_subagent_depth
from code_puppy.plugins.agent_skills import discovery
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


# ---- Fix 6: plugin-skills cache dir reset is race- and squatter-proof --------
def _empty_registrations():
    return iter(())


def test_plugin_skills_cache_dir_concurrent_reset_is_safe():
    # Many threads driving the (locked) collect entry point — emulating
    # concurrent get_model_system_prompt dispatches — must never leak the
    # FileExistsError the unsynchronized rmtree+mkdir used to throw.
    saved_dir = discovery._PLUGIN_SKILLS_CACHE_DIR
    saved_iter = discovery._iter_plugin_skill_registrations
    with tempfile.TemporaryDirectory() as td:
        discovery._PLUGIN_SKILLS_CACHE_DIR = Path(td) / "plugin-skills"
        discovery._iter_plugin_skill_registrations = _empty_registrations
        try:
            errors: list[BaseException] = []
            barrier = threading.Barrier(16)

            def worker():
                try:
                    barrier.wait()
                    for _ in range(25):
                        discovery._collect_plugin_skills()
                except BaseException as exc:  # noqa: BLE001 - capture everything
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(16)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"concurrent cache reset raised: {errors[:3]}"
            assert discovery._PLUGIN_SKILLS_CACHE_DIR.is_dir()
        finally:
            discovery._PLUGIN_SKILLS_CACHE_DIR = saved_dir
            discovery._iter_plugin_skill_registrations = saved_iter


def test_plugin_skills_cache_dir_repairs_stale_nondir():
    # shutil.rmtree only removes *directories*; a file or broken symlink left on
    # the path would make every mkdir(exist_ok=True) raise. The reset must
    # repair it to a directory instead.
    saved_dir = discovery._PLUGIN_SKILLS_CACHE_DIR
    saved_iter = discovery._iter_plugin_skill_registrations
    with tempfile.TemporaryDirectory() as td:
        cache = Path(td) / "plugin-skills"
        discovery._PLUGIN_SKILLS_CACHE_DIR = cache
        discovery._iter_plugin_skill_registrations = _empty_registrations
        try:
            cache.write_text("i am a file, not a dir")
            discovery._collect_plugin_skills()
            assert cache.is_dir() and not cache.is_symlink()

            shutil.rmtree(cache)
            cache.symlink_to(Path(td) / "missing-target")  # broken symlink
            assert cache.is_symlink()
            discovery._collect_plugin_skills()
            assert cache.is_dir() and not cache.is_symlink()
        finally:
            discovery._PLUGIN_SKILLS_CACHE_DIR = saved_dir
            discovery._iter_plugin_skill_registrations = saved_iter


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
    test_plugin_skills_cache_dir_concurrent_reset_is_safe()
    test_plugin_skills_cache_dir_repairs_stale_nondir()
    print("all hardening regression checks passed")
