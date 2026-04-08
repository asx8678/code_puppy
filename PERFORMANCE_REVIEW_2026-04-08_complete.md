# Python Performance Review — code_puppy (Complete Sweep)

**Date:** 2026-04-08 (Part 2 — Full Sweep Extension)
**Reviewer:** planning-agent-019d6e
**Scope:** 14 modules (~10,733 lines), extending the morning's focused review
**Methodology:** Orchestrated via code-scout → python-reviewer × 2 (parallel, 3 batches) → planning-agent (synthesis)
**Companion document:** `PERFORMANCE_REVIEW_2026-04-08.md` (31 findings across 8 hot-path modules, earlier today)

---

## 📑 Executive Summary

This review extends the morning's hot-path review by (a) covering **14 previously-unreviewed modules** and (b) applying a **memory-focused re-review** to the 8 modules covered earlier. It delivers **87 new findings** with **zero overlap** with the companion document.

| Severity | Part 1 (Extension) | Part 2 (Memory Re-review) | **Total** |
|----------|-------------------|--------------------------|----------|
| **High** | 22 | 6 | **28** |
| **Medium** | 30 | 4 | **34** |
| **Low** | 25 | 0 | **25** |
| **Subtotal** | 77 | 10 | **87** |

**Combined with morning review:** **118 total findings** (32 High, 49 Medium, 37 Low).

### 🏆 Top 10 Highest-Leverage Fixes (new in this review)

Ranked by (impact × call frequency × estimated savings):

1. **SR-H1** — `stream_renderer._update_rate` reactive cascade fires ~10 DOM queries + 4 layouts per streaming token. Throttle to 5 Hz. **~40-60% streaming CPU reduction.**
2. **APP-H2** — `tui/app.py:556` calls **synchronous `handle_command`** inside async `_handle_slash_command`, blocking the Textual event loop. Wrap in `asyncio.to_thread`. **Eliminates UI freezes.**
3. **APP-H1** — `write_to_chat` does `query_one("#chat-log")` per call, hammered per-token. Cache widget refs in `on_mount`. **Kills ~5/sec DOM traversals.**
4. **MEM-RC-H1** — `request_cache` holds full httpx.Request bodies: **~20 MB retained per Claude client** for 5 min. Cache bytes not Request objects, or enforce byte budget.
5. **FM-H1** — `_replace_in_file` triple-join rebuild + `modified_lines` cache invalidated every iteration. Slice-assign + single join. **100-300ms on multi-replacement large files.**
6. **CM-H2** — `_find_best_window` joins every window BEFORE length filter. Prefix-sum line lengths. **10-40× speedup on fuzzy edits.**
7. **AT-H1** — `_save_session_history` + `_load_session_history` are **sync on event loop**. Wrap in `asyncio.to_thread`. **Unblocks parallel sub-agents.**
8. **AT-H2** — `_sanitize_messages_for_dbos` does JSON round-trip per invoke on event loop (3× total serialization with save path). Delete or fold into save path.
9. **FO-H1** — `list_files` does 3-5 stat syscalls per file where 1 `os.stat` suffices. **~40ms per 1k-file listing.**
10. **MEM-SS-H1** — `save_session_async` unbounded executor queue + closure captures live history by reference + no atexit shutdown. **Silent data loss at Ctrl+C + old history pinned via closure.**

### 🎯 Cross-Cutting Patterns Observed

1. **Lazy imports in hot loops** — found in 10+ locations across `_core_bridge.py:98`, `agent_tools.py:170,306,366`, `file_modifications.py:200,340,405,695`, `stream_renderer.py:100,158,192`, `message_bridge.py:150,181,220`, `gemini_model.py:97,118`, `tui/app.py:554+screens`, `completion.py:93`. All should be hoisted to module top.
2. **Non-atomic file writes** — `config.py:506,~720,~485,~860`, `file_modifications.py:~355,~415,~695`. None use `persistence.atomic_write_text`. Crash-unsafe AND duplicated temp-file logic.
3. **Sync I/O in async paths** — `agent_tools.py:280,341`, `tui/app.py:556`, entire `persistence.py` API. Event-loop blocking.
4. **DOM query repetition in TUI** — 42 `query_one` calls in `tui/app.py`, per-message queries in `message_bridge.py`, per-token queries in `stream_renderer.py`. Cache widget refs on `on_mount`.
5. **Cache-bypassing writers in config.py** — `set_model_name`, `clear_model_settings`, `get_all_agent_pinned_models` create fresh `ConfigParser()` instances, ignoring the cached parser.
6. **Multi-stat-per-file** — `file_operations.py:281-298` does 4-5 stat calls where 1 suffices.
7. **Closure retention in background tasks** — `session_storage.py` autosave closures capture live references that can pin cleared data.

---

# Part 1: Extension Findings (New Modules)

## command_runner.py (1701 lines) — 10 findings

Behavioral intent: wraps `subprocess.Popen` with streaming output, timeouts, Ctrl-X/C cancellation, command validation, async dispatch. Perf hot spots: cancellation paths, output-draining threads, per-call micro-costs.

### [CR-H1] `_kill_process_group` blocks up to 2.7s in sequential `time.sleep()` — HIGH
- **Location**: `command_runner.py:446,455,465,468,471,485`
- **Issue**: POSIX: `sleep(1.0) → sleep(0.6) → sleep(0.5) → 3× sleep(0.2)` = **2.7s blocking per process**. Killing 5 hung processes on Ctrl-X = **~13.5s frozen UI**.
- **Fix**: Use `Popen.wait(timeout=)` with exponential budget (0.3s → 0.2s → 0.1s = 0.6s total). Parallelize across processes with a ThreadPool.
- **Savings**: ~2.5s × N procs per Ctrl-X.

### [CR-H2] Windows streaming readers busy-poll with `time.sleep(0.1)` — HIGH
- **Location**: `command_runner.py:~965, ~1030` (read_stdout/read_stderr Windows branches)
- **Issue**: Two reader threads × 10 Hz wake-ups per shell command + 100ms EOF lag. POSIX has similar 100ms stop-event lag.
- **Fix**: Use blocking `readline()` on Windows (threads are for blocking); close pipes from cleanup to wake them. POSIX: use `stop_event.wait(0.1)`.
- **Savings**: ~5% CPU per shell + 100ms EOF latency.

### [CR-M1] Ctrl-X listener 20 Hz poll always-on during shell execution — MEDIUM
- **Location**: `command_runner.py:654, 680`
- **Issue**: POSIX `select.select([stdin], [], [], 0.05)` and Windows `time.sleep(0.05)` busy-waits for duration of every command.
- **Fix**: POSIX: raise timeout to 0.25s (select wakes on keypress anyway). Windows: use `stop_event.wait(0.1)`.
- **Savings**: ~3-5% CPU during shell execution.

### [CR-M2] `_validate_forbidden_chars` Python char loop — MEDIUM
- **Location**: `command_runner.py:144`
- **Issue**: `for i, char in enumerate(command): if char in FORBIDDEN_CHARS` — walks every byte in Python on every shell call.
- **Fix**: Module-level compiled regex `_FORBIDDEN_CHARS_RE`, only iterate on the rare failure path to build error message.
- **Savings**: ~80-120μs per 8KB command.

### [CR-M3] `_validate_shlex_parse` redundant `any(token.strip())` second pass — LOW-MED
- **Location**: `command_runner.py:196`
- **Fix**: Remove; `shlex.split` already drops whitespace-only tokens and `validate_shell_command` rejects empty input.

### [CR-M4] Lazy imports sprinkled across `run_shell_command` (4 sites) — LOW-MED
- **Location**: `command_runner.py:1280,1440,1455,1530`
- **Fix**: Hoist `get_security_boundary`, `get_yolo_mode`, `get_puppy_name` to module top; cache `messaging.spinner` module lookup.

### [CR-M5] `list(stdout_lines)[-256:]` no-op slice done 5× per command — LOW
- **Location**: `command_runner.py:1146,1147,1179,1180,1195,1197`
- **Issue**: `stdout_lines` is already `deque(maxlen=256)` — the `[-256:]` is dead work.
- **Fix**: `"\n".join(stdout_lines)` directly (str.join accepts deques).

### [CR-L1] `safe_execute_subprocess` is dead code — LOW
- **Location**: `command_runner.py:229`
- **Fix**: Delete; zero callers in repo.

### [CR-L2] `_emit_*_batch` is batch-in-name-only (per-line lock acquires) — LOW-MED
- **Location**: `command_runner.py:~880`
- **Fix**: Add `emit_shell_lines(list, stream)` to message bus with single lock acquire.
- **Savings**: ~10× lock contention reduction on noisy commands (e.g., `pip install -v`).

### [CR-L3] `preexec_fn=os.setsid` vs `process_group=0` — LOW
- **Location**: `command_runner.py:1572`
- **Fix**: Use Python 3.11+ `Popen(process_group=0)` instead of `preexec_fn=os.setsid`. Uses `posix_spawn` (2-3× faster) and avoids fork-in-threaded-app deadlock risk.

---

## common.py (1258 lines) — 9 findings

### [CM-H1] `_matches_compiled` runs O(path-depth) regex + Path allocs per path — HIGH
- **Location**: `common.py:454`
- **Issue**: 3 full-path matches + `for i in range(1, len(parts)): sub = str(Path(*parts[i:])); 2 more matches per suffix`. For depth-7 path: **15 regex matches + 6 Path allocs** per ignore check. No caching; walks 10k-file tree hitting same patterns thousands of times.
- **Fix**: Two options: (A) `@lru_cache(maxsize=8192)` on `should_ignore_path` (cheap one-line win). (B) Rewrite `_compile_patterns` to use a single un-anchored regex allowing any-prefix via `(?:(?:^|.*/){body})`.
- **Savings**: 5-20× on deep trees.

### [CM-H2] `_find_best_window` joins every window BEFORE length filter — HIGH
- **Location**: `common.py:1197,1218`
- **Issue**: Main loop `for i in range(max_start):` does `"\n".join(haystack_lines[i:window_end])` per iteration, then length-filters AFTER allocation, then runs JW similarity. For 2000-line haystack + 10-line needle = ~1990 joins × 300-1000 bytes each per call. `edit_file` calls this once per replacement per file.
- **Fix**: Prefix-sum cumulative line lengths once, O(1) window length pre-filter, skip join when out of range.
- **Savings**: **10-40× on large files.**

### [CM-M1] `asyncio.sleep(0.3) + asyncio.sleep(0.1)` per user approval prompt — MEDIUM (HIGH UX)
- **Location**: `common.py:1080,1098`
- **Issue**: **400ms forced wait per approval** as spinner-flush timing hack. Over a 100-approval session = 40 seconds of user staring at nothing.
- **Fix**: Event-driven `_wait_for_spinner_quiet(max_wait=0.1)` + `asyncio.sleep(0)` yield.
- **Savings**: Up to 400ms × N approvals.

### [CM-M2] `_get_token_color` linear scan over TOKEN_COLORS per token — MEDIUM
- **Location**: `common.py:580`
- **Fix**: `@lru_cache(maxsize=256)` on `_get_token_color` — Pygments token types are interned/hashable.

### [CM-M3] `_highlight_code_line` re-invokes Pygments lexer per line — MEDIUM
- **Location**: `common.py:592`
- **Fix**: Batch-lex the entire code block once, slice tokens by newlines.
- **Savings**: 5-10× on multi-hundred-line diffs.

### [CM-M4] `get_formatted_text` rebuilds HTML escapes per keystroke — LOW-MED
- **Location**: `common.py:829` (arrow_select_async)
- **Fix**: Hoist invariant escapes out of the closure.

### [CM-M5] `arrow_select`/`get_user_approval` sync wrappers force thread hop + new event loop — MEDIUM
- **Location**: `common.py:925,949`
- **Issue**: `run_async_sync` spawns a ThreadPool worker + creates a new event loop per call. Called from async `handle_edit_file_permission` → 2 event loops per prompt.
- **Fix**: Make file permission chain async end-to-end; raise RuntimeError if sync wrappers called from an active loop.

### [CM-L1] `IGNORE_PATTERNS` double-dedup — NEGLIGIBLE
- **Fix**: Use `tuple(dict.fromkeys(...))` once.

### [CM-L2] `generate_group_id` uses MD5 (slow + FIPS-unfriendly) — LOW
- **Fix**: `blake2b(digest_size=4)` or skip hashing and use `secrets.token_hex(4)` directly.

---

## file_operations.py (977 lines) — 8 findings

### [FO-H1] Stat-cascade: 3-5 syscalls per file where 1 `os.stat` suffices — HIGH
- **Location**: `file_operations.py:273-305`
- **Issue**: `os.path.exists` + `os.path.isfile` + `os.path.isdir` + `os.path.getsize` + `os.stat` — all called on every ripgrep-listed file. `os.path.exists` is dead weight since `rg --files` only emits existing.
- **Fix**: Single `os.stat()`, derive type from `stat.S_ISREG/S_ISDIR(st.st_mode)` and size from `st.st_size`.
- **Savings**: ~40ms per 1000-file listing.

### [FO-H2] 213 one-line writes to tempfile per `list_files`/`_grep` call — HIGH
- **Location**: `file_operations.py:246-259, 813-822`
- **Issue**: `for pattern in DIR_IGNORE_PATTERNS: f.write(f"{pattern}\n")` — 213 tiny writes per invocation. `_grep` path is fully deterministic yet recreated every call.
- **Fix**: (A) `@lru_cache(maxsize=1)` on `_grep_ignore_file()` with `atexit` cleanup. (B) `list_files` path: batch with `"\n".join(filtered) + "\n"`.
- **Savings**: ~1-3ms per call; grep version = zero writes after first call.

### [FO-H3] O(depth²) parent-path construction per file — MEDIUM-HIGH
- **Location**: `file_operations.py:317`
- **Issue**: `for i in range(len(path_parts)): partial_path = os.sep.join(path_parts[:i+1])` — each iter joins a growing slice from scratch.
- **Fix**: Accumulate incrementally; track depth with counter.
- **Savings**: ~5-15ms on deep trees.

### [FO-M1] `sensitive_dir_prefixes`/`_exact_files`/`_extensions` rebuilt per `validate_file_path` call — MEDIUM
- **Location**: `file_operations.py:509-542`
- **Fix**: Hoist to module-level `frozenset`/`tuple` constants with `_HOME = os.path.expanduser("~")`.
- **Savings**: ~50-150ms across a session.

### [FO-M2] `validate_file_path` called twice per `_read_file` — MEDIUM
- **Location**: `file_operations.py:608, 630`
- **Fix**: Pass `_skip_validation=True` sentinel from async wrapper to sync worker.
- **Savings**: ~20-50μs per read × thread-pool slot held longer.

### [FO-M3] Per-char Python loop for surrogate cleanup fallback — MEDIUM (cold path)
- **Location**: `file_operations.py:676-680, 748-752`
- **Issue**: `"".join(char if ord(char) < 0xD800 or ord(char) > 0xDFFF else "\ufffd" for char in content)` — Python-level per-char walk.
- **Fix**: Module-level `_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")` + `re.sub(r"\ufffd", text)`.
- **Savings**: 40-100× speedup on 1MB inputs when triggered.

### [FO-M4] `sorted_results` iterated twice for UI + LLM text — LOW
- **Location**: `file_operations.py:428, 452`
- **Fix**: Single pass builds both `file_entries` and `output_lines`.

### [FO-L1] Lazy import of `estimate_token_count` per read — LOW
- **Fix**: Hoist to module top.

---

## file_modifications.py (933 lines) — 7 findings

### [FM-H1] `_replace_in_file` triple-join rebuild + cache invalidated every iter — HIGH
- **Location**: `file_modifications.py:296-347`
- **Issue**: 3 slices + 3 joins + outer join = copying file body **3× per replacement**. Then `modified_lines = None` forces re-splitlines on next iter. For 5k-line file × 5 fuzzy replacements = ~125k line copies + 5 re-splits.
- **Fix**: `modified_lines[start:end] = new_lines` slice-assignment; keep cache alive across iterations; single final `"\n".join(modified_lines)`.
- **Savings**: **100-300ms on multi-replacement large files.**

### [FM-H2] `splitlines(keepends=True)` called 2× per diff across 4 sibling functions — MEDIUM
- **Location**: `file_modifications.py:243,366,418,671`
- **Fix**: Cache `original_keepends = original.splitlines(keepends=True)` once per operation.
- **Savings**: ~15-30ms per 1MB diff.

### [FM-H3] `_delete_file` reads entire file + runs full `unified_diff` just to render "everything removed" — MEDIUM
- **Location**: `file_modifications.py:655-679`
- **Fix**: Size check; for files > 256KB emit a summary diff instead of full content walk.
- **Savings**: Seconds on large files.

### [FM-M1] Surrogate-sanitize block copy-pasted 4× across sibling functions — MEDIUM
- **Location**: `file_modifications.py:228,286,413,662`
- **Fix**: Module-level `_sanitize_surrogates(text)` helper shared with `file_operations._sanitize_string`.

### [FM-M2] `get_diff_context_lines` lazy-imported 4 places — LOW
- **Location**: `file_modifications.py:239,362,407,667`
- **Fix**: Module-top import + optional `@lru_cache(maxsize=1)` wrapper.

### [FM-M3] Triple transformation of `replacements` (dict→dict→Pydantic) — LOW
- **Location**: `file_modifications.py:880,893`
- **Fix**: Pass inbound dicts straight through; only build Pydantic model if callbacks are registered.

### [FM-L1] Mutable default `replacements: list = []` — LOW
- **Fix**: Use `replacements: list | None = None`; initialize inside body.

---

## config.py (2020 lines) — 7 findings

### [CFG-H1] `get_all_model_settings` / `get_effective_model_settings` O(N) scan + N+1, UNCACHED on hot path — HIGH
- **Location**: `config.py:1088, 1151`
- **Issue**: Iterates every config key with `.startswith(prefix)` + inline type parsing. Called from `model_factory.py:170,402,448` and 3 other hot sites **per model selection / per tool registration / per model switch**.
- **Fix**: Add `_model_settings_cache: dict[str, dict]` keyed by model name, clear in `_invalidate_config`. Hoist `len(prefix)` out of loop. Use set comprehension for `model_supports_setting` filter.
- **Savings**: 10-50× on model-settings lookups.

### [CFG-H2] `auto_save_session_if_enabled` tokenizes entire history on MAIN THREAD before "async" save — HIGH
- **Location**: `config.py:1815`
- **Issue**: Docstring claims "happens in background thread" but `total_tokens = sum(estimate_tokens_for_message(msg) for msg in history)` runs synchronously RIGHT BEFORE the async call. Defeats the purpose of `save_session_async`.
- **Fix**: Delete the precomputation; let `save_session_async` own token counting via `token_estimator` callback.
- **Savings**: 5-50ms per agent turn, scales with history length.

### [CFG-M1] Three writers bypass config cache with fresh `ConfigParser.read()` — MEDIUM
- **Location**: `config.py:893 (set_model_name), 1136 (clear_model_settings), 1544 (get_all_agent_pinned_models)`
- **Issue**: `get_all_agent_pinned_models` runs per tab-completion keystroke, each call = full disk re-parse.
- **Fix**: Use `_get_config()` + dict comprehension. Atomic writes via `persistence.atomic_write_text`.
- **Savings**: 200μs-1ms per call.

### [CFG-M2] `_invalidate_config` hand-lists 33 `cache_clear()` calls — MEDIUM
- **Location**: `config.py:116`
- **Issue**: Maintenance hazard: every new cached getter must be manually registered or silently stale-caches.
- **Fix**: `_CACHED_GETTERS: list` registry pattern; factory functions auto-register.

### [CFG-L1] Invalidate forces disk re-read when parser is already fresh — LOW
- **Fix**: After `set_config_value`, bump mtime instead of nuking `_state.config_cache`.

### [CFG-L2] `get_default_config_keys` rebuilds list + loops banner dict per call — LOW
- **Fix**: Module-level `_DEFAULT_CONFIG_KEYS: tuple` computed once.

### [CFG-L3] `_sanitize_model_name_for_key` chains three `str.replace()` — LOW
- **Fix**: `str.translate(str.maketrans({".": "_", "-": "_", "/": "_"}))` — single C-level pass.

---

## agent_tools.py (806 lines) — 6 findings

### [AT-H1] `_save_session_history` + `_load_session_history` SYNC on event loop — HIGH
- **Location**: `agent_tools.py:284, 345` (called from async `invoke_agent`)
- **Issue**: Both do `ModelMessagesTypeAdapter.dump_python/validate_python` (CPU-bound pydantic walk) + `msgpack.packb/unpackb` + file I/O **directly on the event loop**. For 200-message history = 100+ms block per save/load. Serializes all parallel sub-agents on the same thread.
- **Fix**: Split into `_sync` helpers + `async` wrappers using `asyncio.to_thread`. Await in `invoke_agent`.
- **Savings**: 50-200ms per save/load, unblocks parallel sub-agents.

### [AT-H2] `_sanitize_messages_for_dbos` JSON round-trip on event loop (3× total serialization) — HIGH
- **Location**: `agent_tools.py:158`
- **Issue**: `dump_json` → `validate_json` is a full bytes round trip. Then `_save_session_history` `dump_python` does the same work AGAIN. Triple pydantic validation per invoke when DBOS enabled (default ON).
- **Fix**: Delete entirely — let the save path do the one serialization that's already there. OR use `dump_python(mode="json") → validate_python` (30% faster) + `asyncio.to_thread`.
- **Savings**: 20-100ms per invoke when DBOS on.

### [AT-M1] Metadata `.txt` read-modify-write: race + sync I/O + non-atomic — MEDIUM
- **Location**: `agent_tools.py:315-340`
- **Fix**: Fold metadata into the msgpack payload; drop the separate `.txt` file.

### [AT-M2] `_get_subagent_sessions_dir` does mkdir+stat per call — MEDIUM
- **Location**: `agent_tools.py:272`
- **Fix**: `@cache` the function — runs mkdir once per process.
- **Savings**: ~20μs per save/load.

### [AT-L1] `_sanitize_session_id` inline regex instead of compiled module-level — LOW
- **Fix**: `_SESSION_ID_NORMALIZE_RE`, `_SESSION_ID_COLLAPSE_RE` at module top.

### [AT-L2] `ModelMessagesTypeAdapter` lazy-imported 3× — LOW
- **Location**: `agent_tools.py:170,306,366`
- **Fix**: Hoist to module-top import.

---

## gemini_model.py (754 lines) — 5 findings

### [GM-H1] Tool schema `deepcopy` storm per request — HIGH
- **Location**: `gemini_model.py:103, 118, 184, 468`
- **Issue**: `_sanitize_schema_for_gemini` starts with `copy.deepcopy(schema)`, then `resolve_refs` deepcopies each `$ref`, then `_flatten_union_to_object_gemini` deepcopies again. All runs **per tool, per request**. For 20 tools × discriminated unions = 100+ deepcopies per request. **No caching** despite tool schemas being static.
- **Fix**: `_SCHEMA_SANITIZE_CACHE: dict[int, dict]` keyed by `id(schema)`. Cache `_build_tools()` result on `GeminiModel` instance keyed by `tuple(id(t) for t in tools)`.
- **Savings**: 5-50ms per request (scales with tool count).

### [GM-H2] `json.loads` per SSE chunk in streaming hot path — HIGH
- **Location**: `gemini_model.py:665`
- **Fix**: Use `orjson.loads` (3-5× faster) with fallback to stdlib. Also switch to `aiter_bytes` for zero-decode path.
- **Savings**: 1-10ms per streaming turn.

### [GM-M1] Lazy `import copy` inside hot helpers — MEDIUM
- **Location**: `gemini_model.py:57, 112`
- **Fix**: Module-top import.

### [GM-M2] `_map_user_prompt` is `async` with zero awaits — MEDIUM
- **Location**: `gemini_model.py:314`
- **Issue**: Every call creates a coroutine object + scheduler hop for no reason.
- **Fix**: Make sync; drop `await` at call site.

### [GM-L1] `_get_headers` / `_build_generation_config` rebuild identical dicts per request — LOW
- **Fix**: Cache in `__init__`; `_gen_config_cache` keyed by `id(model_settings)`.

---

## persistence.py (225 lines) — 3 findings

### [PS-H1] All file I/O is SYNCHRONOUS, blocks asyncio event loop — HIGH
- **Location**: `persistence.py:91,125,198,215`
- **Issue**: Every function is `def`, yet `agent_tools.py:313` calls `atomic_write_msgpack` **from async context** on every message commit. 1-5MB sessions → single-digit ms → hundreds of ms on HDD/encrypted FS. Every ms is a paused event loop.
- **Fix**: Add `atomic_write_text_async`, `atomic_write_bytes_async`, `atomic_write_msgpack_async`, `read_json_async`, `read_msgpack_async` — all `asyncio.to_thread` wrappers.

### [PS-M1] Duplicate `mkdir(parents=True)` per write — MEDIUM
- **Location**: `persistence.py:61,82,117`
- **Issue**: `atomic_write_text` calls mkdir, then `_atomic_replace` calls mkdir again. Two syscalls per write where one suffices.
- **Fix**: Delete the mkdir in `_atomic_replace`; document that caller is responsible for parent dir.

### [PS-L1] Use `orjson` for `atomic_write_json` — LOW
- **Fix**: Optional `orjson.dumps(data, option=orjson.OPT_INDENT_2)` with stdlib fallback.

---

## _core_bridge.py (179 lines) — 4 findings

### [CB-H1] `from pydantic_ai.messages import ModelRequest` lazy INSIDE hot serializer — HIGH
- **Location**: `_core_bridge.py:100`
- **Issue**: Called per message via `serialize_messages_for_rust` list comprehension. For 1000-message history × 5 call sites per turn = ~5000 redundant `sys.modules` dict lookups per turn.
- **Fix**: Hoist `from pydantic_ai.messages import ModelRequest` to module top.
- **Savings**: 2-5ms per turn.

### [CB-M1] `hasattr`-then-direct-access is SLOWER than `getattr` with default — MEDIUM
- **Location**: `_core_bridge.py:126-131`
- **Issue**: Comment claims `hasattr + direct access` is faster than `getattr`, but when the attribute IS present (common case), `hasattr` pays for two lookups. `getattr(part, "content", None)` is ~40% faster.
- **Fix**: Replace all 4 `hasattr/direct` pairs with `getattr(part, name, None)`.
- **Savings**: ~1ms per 1K-msg batch.

### [CB-M2] `str(args)` produces invalid JSON for Rust consumer — MEDIUM (+ correctness)
- **Location**: `_core_bridge.py:140`
- **Issue**: `str(dict)` produces Python repr format with single quotes, not valid JSON. Either the Rust side is lenient (latent bug) or currently failing silently.
- **Fix**: `json.dumps(args, separators=(",", ":"))` — compact valid JSON.
- **Note**: Verify Rust parser expectation before shipping.

### [CB-L1] `sort_keys=True` on per-part serialization — LOW
- **Location**: `_core_bridge.py:159,163`
- **Fix**: Drop unless Rust side needs canonical form (verify).

---

## tui/app.py (801 lines) — 5 findings

### [APP-H1] `write_to_chat` does `query_one("#chat-log")` per call — HIGH
- **Location**: `app.py:778` (called per-token from `stream_renderer`)
- **Fix**: Cache `self._chat_log`, `self._input_widget`, `self._info_bar`, `self._completion_overlay` in `on_mount`. Ripgrep-replace all 42 `query_one` call sites.
- **Savings**: Kills ~5/sec DOM traversals during streaming.

### [APP-H2] Sync `handle_command` blocks event loop inside async handler — HIGH
- **Location**: `app.py:556`
- **Issue**: Inside `async def _handle_slash_command`, `result = handle_command(command)` is a SYNCHRONOUS call that can hit disk/shell/HTTP. Textual event loop frozen during execution. `await asyncio.sleep(0.1)` on line 562 is a bandaid, not a fix.
- **Fix**: `await asyncio.to_thread(handle_command, command)`. Drop the `sleep(0.1)` to `sleep(0)`.

### [APP-M1] `_handle_slash_command` is a 15-branch if/elif chain — MEDIUM
- **Location**: `app.py:413-537`
- **Fix**: Table-driven dispatch via `_SCREEN_COMMANDS: dict[str, tuple[factory, callback]]`.

### [APP-M2] `_get_overlay` runs DOM query per keystroke — MEDIUM
- **Location**: `app.py:57, 84, 90, 97`
- **Fix**: Cache `self._overlay` and `self._option_list` in `PuppyInput.on_mount`.

### [APP-L1] Lazy screen imports sprawled across 15+ sites — LOW
- **Fix**: Folded into APP-M1's dispatch table via `_import_and_push(dotted, cls)` factories.

---

## tui/message_bridge.py (325 lines) — 4 findings

### [MB-H1] Lazy imports + `query_one` per queued message — HIGH
- **Location**: `message_bridge.py:150,198,262,315`
- **Issue**: `_render_queue_message` is the highest-frequency callback during streaming. Imports `MessageType`, `Markdown`, `Text` per call + `query_one("#chat-log")` per message.
- **Fix**: Module-top imports; cache `self._chat_log` on bridge start.
- **Savings**: ~1000 imports+queries eliminated per message burst.

### [MB-H2] `TUIConsole.write` runs `Text.from_ansi` unconditionally — MEDIUM
- **Location**: `message_bridge.py:315`
- **Fix**: Fast-path `if "\x1b" not in stripped: chat.write(stripped); return`. Skip ANSI parser for plain text.

### [MB-M1] O(N) if/elif chain on `msg_type` — LOW-MED
- **Location**: `message_bridge.py:160-195`
- **Fix**: `_PLAIN_STYLES: dict[MessageType, str]` template dict.

### [MB-L1] `_ANSI_RE` misses OSC/DECSET sequences — LOW (correctness)
- **Fix**: Use `r"\x1b\[[0-?]*[ -/]*[@-~]"` or delegate to `rich.ansi.AnsiDecoder`.

---

## tui/stream_renderer.py (271 lines) — 5 findings — THE HOTTEST PATH

### [SR-H1] Reactive watcher cascade fires ~10 DOM queries + 4 layouts per token — HIGH
- **Location**: `stream_renderer.py:264` — `_update_rate`
- **Issue**: Every text delta sets `app.token_rate` AND `app.status_message`, triggering reactive watchers that `query_one("#info-bar")`, trigger 4 sub-field reactive assignments with `layout=True`, call `get_current_agent()` + `get_active_model()` on **every token**. At 100 tok/s = 1000 DOM queries + 400 layouts per second.
- **Fix**: Throttle to 5 Hz (`_RATE_UPDATE_INTERVAL = 0.2`). Decouple spinner rotation (2 Hz) from rate updates.
- **Savings**: **~40-60% of streaming CPU.**

### [SR-H2] Lazy `pydantic_ai` imports inside `handle_event` per token — HIGH
- **Location**: `stream_renderer.py:100,152,186`
- **Fix**: Hoist all `PartDeltaEvent`, `PartEndEvent`, `PartStartEvent`, `TextPart*`, `ThinkingPart*`, `ToolCallPart*` to module top with `_PYDANTIC_AI_OK` guard.
- **Savings**: ~5% per-token CPU.

### [SR-H3] `self._text_buffer[idx] += delta.content_delta` defeats CPython in-place optimization — MEDIUM-HIGH
- **Location**: `stream_renderer.py:194`
- **Issue**: `dict[k] += str` desugars to `dict[k] = dict[k] + str` — bumps refcount before add, kills in-place optimization. O(n²) reallocations per flush.
- **Fix**: `_text_buffer: dict[int, list[str]]` + `frags.append()` + `"".join(frags)` at flush time. Also check `"\n" in delta.content_delta` (small) instead of `"\n" in buf` (growing).

### [SR-M1] `escape()` + f-string per thinking delta — MEDIUM
- **Location**: `stream_renderer.py:192`
- **Fix**: Apply buffering strategy to thinking parts too; escape + wrap only at flush.

### [SR-M2] `StreamRenderer` has no `__slots__` — LOW-MED
- **Location**: `stream_renderer.py:67`
- **Fix**: Add `__slots__` with 13 attributes. ~5-10% attribute access speedup on hot path.

---

## tui/completion.py (254 lines) — 4 findings

### [COMP-H1] Unbounded `glob.glob` + `os.path.isdir` per keystroke for `@path` — HIGH
- **Location**: `completion.py:200-222`
- **Issue**: On EVERY character typed after `@`, runs `glob.glob`, then `os.path.isdir` on EVERY match, THEN applies `items[:50]`. Big repo + type `@s` → thousands of stat syscalls per keystroke → frozen TUI.
- **Fix**: Use `os.scandir` with `entry.is_dir(follow_symlinks=False)` (cached from readdir). Early-exit at 50 matches BEFORE stat. Filter-then-sort.
- **Savings**: Order-of-magnitude on big repos.

### [COMP-H2] `ModelFactory.load_config()` + `get_unique_commands()` + `get_available_agents()` called per keystroke — HIGH
- **Location**: `completion.py:93,130,146,161`
- **Fix**: Module-level `@lru_cache(maxsize=1)` helpers: `_cached_command_names`, `_cached_model_names`, `_cached_agent_names`. Expose `invalidate_completion_caches()` for config reload.
- **Savings**: ~9× speedup typing `/model gpt` (9 JSON parses → 1).

### [COMP-M1] `sorted(os.listdir)` + stat per entry in `_complete_directories` — MEDIUM
- **Location**: `completion.py:241`
- **Fix**: Same `os.scandir` pattern as COMP-H1.

### [COMP-L1] `CompletionItem` dataclass missing `slots=True` — LOW
- **Fix**: `@dataclass(slots=True)`.

---

# Part 2: Memory-Focused Re-Review (Already-Covered Modules)

These findings are genuinely new — they complement (do not duplicate) the morning review. Each finding explicitly notes its dedup status.

## [MEM-CB-H1] `on_pre_tool_call` pins parent via `_parent_ref` + discards ContextVar Token — HIGH
- **Location**: `callbacks.py:538-556`
- **Issue**: (1) `child.metadata["_parent_ref"] = parent` installs strong retention chain — any plugin that snapshots child contexts pins parent metadata forever. (2) Cleanup only runs if `ctx.component_type == "tool" and ctx.component_name == tool_name` — proxies/decorators that rename tools leak the ref. (3) `set_current_run_context(child)` returns a Token that is silently discarded, breaking proper unwind and leaking context into spawned Tasks (contextvars are copied on Task creation).
- **Fix**: Use `weakref.ref(parent)` to break retention; use `_current_run_context.set(child)` returning Token; store token on child for post-hook reset.
- **Dedup**: Genuinely new (distinct from H1/H2/M1/M2/L1).

## [MEM-CCC-H1] Module-level `@lru_cache` on JWT decoders retains raw bearer tokens — HIGH
- **Location**: `claude_cache_client.py:128-168` — `_get_jwt_iat`, `_get_jwt_exp`
- **Issue**: `@lru_cache(maxsize=16)` stores full JWT strings as keys — ~1.5KB per token × 16 slots × 2 functions = **~49KB of retained secrets**. OAuth refresh rotates tokens but old bearers stay until 16 new unique tokens push them out (often "never" for quiet installs).
- **Fix**: Hash-based cache key via `hashlib.sha256(token.encode())[:16]`. Single `_get_jwt_claims` returning `(iat, exp)` tuple — eliminates duplicate parse.
- **Dedup**: Genuinely new (distinct from M7, which is the *instance-level* tuple cache).

## [MEM-CCC-M1] `_is_cloudflare_html_error` double-allocates decoded+lowered body — MEDIUM
- **Location**: `claude_cache_client.py:704-718`
- **Fix**: ASCII `bytes.lower()` on 8KB-capped slice, skip UTF-8 decode entirely.
- **Dedup**: Genuinely new (distinct from M8).

## [MEM-SS-H1] `save_session_async` unbounded executor queue + closure pins live history + no atexit — HIGH
- **Location**: `session_storage.py:26-62`
- **Issue**: (1) `ThreadPoolExecutor(max_workers=1)` with default `SimpleQueue` — unbounded under slow disk. (2) `_do_save` closure captures `history`/`compacted_hashes` by reference — queued saves hold live references, so `/clear` doesn't actually free old history until drain. (3) No `atexit.register(shutdown)` — pending saves dropped on Ctrl+C (silent data loss).
- **Fix**: Snapshot via `list(history)` at submit time; bounded pending queue (`maxsize=4` with oldest-dropped coalescing); `atexit.register(_autosave_shutdown)`.
- **Dedup**: Genuinely new (distinct from H4/M12/L8).

## [MEM-SS-M1] `_load_raw_bytes` full copy on slice instead of memoryview — MEDIUM
- **Location**: `session_storage.py:158-180`
- **Issue**: `msgpack_data = raw[offset + 32:]` copies `len(raw) - 40` bytes. For 5MB session file = peak 2× file size during load.
- **Fix**: `memoryview(raw)[offset+32:]` — `msgpack.unpackb` and `hmac.new` both accept buffer-protocol objects.
- **Dedup**: Genuinely new (distinct from H4/M12/L8).

## [MEM-ARL-H1] `ModelRateLimitState.__post_init__` eagerly allocates unused `asyncio.Queue` — HIGH
- **Location**: `adaptive_rate_limiter.py:84-92`
- **Issue**: Every state instance creates `asyncio.Queue(maxsize=DEFAULT_QUEUE_MAX_SIZE)` (~2376 bytes), but the circuit breaker is **disabled by default** (`DEFAULT_CIRCUIT_BREAKER_ENABLED: bool = False` on line 49). With 50+ models tracked = **~119KB dead weight**; 200+ models = ~475KB.
- **Fix**: `_ensure_queue(state)` lazy helper invoked only when circuit actually opens.
- **Dedup**: Genuinely new (distinct from M3/M4/L2/L3/L4).

## [MEM-MF-H1] `ZaiCerebrasProvider` class defined INSIDE `_build_cerebras` — new type per call — HIGH
- **Location**: `model_factory.py:535-544`
- **Issue**: Every call creates a fresh `type` object (~1KB + method dict + MRO cache + weakref set). Multi-model / round-robin configs generate dead classes that `gc` tracks forever. Also defeats cross-call `isinstance` checks.
- **Fix**: Hoist to module-scope lazy factory `_get_zai_cerebras_provider_class()` with `_ZaiCerebrasProvider: type | None = None` global cache.
- **Dedup**: Genuinely new (distinct from M13/M14/L10/L11/L12).

## [MEM-MF-M1] `_model_config_cache = config.copy()` shallow + asymmetric `MappingProxyType` return — MEDIUM
- **Location**: `model_factory.py:757-763`
- **Issue**: Cache-miss returns `MappingProxyType(config)` (original), cache-hit returns `MappingProxyType(_model_config_cache)` (copy) — different identity. Shallow copy means nested dicts are shared; mutation through `result["gpt-5"]["max_tokens"] = ...` poisons cached version (`MappingProxyType` only protects top level).
- **Fix**: Drop the `.copy()`; nested `_deep_freeze(d)` via dict comprehension of `MappingProxyType` at both cache paths.
- **Dedup**: Genuinely new.

## [MEM-RC-H1] Request cache holds 50-100KB request bodies strongly — ~20MB retained per Claude client — HIGH
- **Location**: `request_cache.py:263-281` + `claude_cache_client.py:251 (_init_request_cache max_size=256, ttl=300)`
- **Issue**: `CachedRequest.request: httpx.Request` pins body bytes. 256 slots × 75KB avg body = **~19MB per client**. Round-robin across 3 Claude models = ~60MB. Stated purpose is header-only optimization, but the memory cost is the body, not headers.
- **Fix**: Option A — cache `CachedContent.content: bytes` only, rebuild Request on lookup. Option B — enforce byte budget (e.g., `MAX_BYTES = 4MB`) instead of count-based eviction.
- **Dedup**: Genuinely new (L6 is `__slots__`, L5 is eviction cadence, M5 is hash compute — none touch body retention).

## [MEM-IL-M1] `list(result.all_messages())` triplicated — MEDIUM
- **Location**: `interactive_loop.py:120, 493, 582`
- **Fix**: Single `_sync_history_from_result(agent, result)` helper. `all_messages()` already returns a list; the `list(...)` wrap is redundant if `set_message_history` takes ownership.
- **Dedup**: Genuinely new (distinct from M15/L9).

---

# 📊 Master Prioritized Summary Table

## All 87 New Findings Ranked by Impact × Frequency

| Rank | ID | Location | Severity | Est. Savings |
|------|----|----|---|---|
| 1 | SR-H1 | `stream_renderer.py:264` | **High** | ~40-60% streaming CPU |
| 2 | APP-H2 | `tui/app.py:556` | **High** | Eliminates UI freezes + 100ms sleep |
| 3 | APP-H1 | `tui/app.py:778` | **High** | Per-token DOM traversals eliminated |
| 4 | MEM-RC-H1 | `request_cache.py:263` | **High** | ~20 MB RSS per Claude client |
| 5 | FM-H1 | `file_modifications.py:296` | **High** | 100-300 ms per multi-replace |
| 6 | CM-H2 | `common.py:1197` | **High** | 10-40× on fuzzy edits |
| 7 | AT-H1 | `agent_tools.py:284,345` | **High** | 50-200 ms per save/load, unblocks parallel subagents |
| 8 | AT-H2 | `agent_tools.py:158` | **High** | 20-100 ms per invoke (DBOS) |
| 9 | FO-H1 | `file_operations.py:273` | **High** | ~40 ms per 1k-file listing |
| 10 | MEM-SS-H1 | `session_storage.py:26` | **High** | Data-loss fix + history retention |
| 11 | COMP-H1 | `completion.py:200` | **High** | Order-of-magnitude on big repos |
| 12 | COMP-H2 | `completion.py:93,130,146,161` | **High** | ~9× on `/model gpt` typing |
| 13 | MB-H1 | `message_bridge.py:150` | **High** | ~1000 ops eliminated per burst |
| 14 | CFG-H1 | `config.py:1088,1151` | **High** | 10-50× model-settings lookups |
| 15 | SR-H2 | `stream_renderer.py:100,152,186` | **High** | ~5% per-token CPU |
| 16 | CR-H1 | `command_runner.py:446` | **High** | ~2.5s × N procs per Ctrl-X |
| 17 | CM-H1 | `common.py:454` | **High** | 5-20× on deep tree scans |
| 18 | GM-H1 | `gemini_model.py:103,468` | **High** | 5-50 ms per request |
| 19 | FO-H2 | `file_operations.py:251,817` | **High** | ~1-3 ms per call (grep = near-zero) |
| 20 | PS-H1 | `persistence.py` (all funcs) | **High** | Unblocks event loop 1-100 ms per save |
| 21 | CFG-H2 | `config.py:1815` | **High** | 5-50 ms per agent turn |
| 22 | CR-H2 | `command_runner.py:965,1030` | **High** (Win) | ~5% CPU + 100ms EOF latency |
| 23 | MEM-CB-H1 | `callbacks.py:538` | **High** | Memory retention + Token idiom bug |
| 24 | MEM-ARL-H1 | `adaptive_rate_limiter.py:84` | **High** | ~2.4 KB × N models (100+ KB) |
| 25 | MEM-CCC-H1 | `claude_cache_client.py:128` | **High** | ~49 KB of retained secrets + sec win |
| 26 | MEM-MF-H1 | `model_factory.py:535` | **High** | ~1 KB class + gc tracker per build |
| 27 | CB-H1 | `_core_bridge.py:100` | **High** | 2-5 ms per turn |
| 28 | GM-H2 | `gemini_model.py:665` | **High** | 1-10 ms per streaming turn |
| 29 | SR-H3 | `stream_renderer.py:194` | Medium-High | 2-4× less alloc per flush |
| 30 | FO-H3 | `file_operations.py:317` | Medium-High | 5-15 ms deep trees |
| 31 | FM-H2 | `file_modifications.py:243+` | Medium | 15-30 ms per MB diff |
| 32 | FM-H3 | `file_modifications.py:655` | Medium | seconds on large deletes |
| 33 | CM-M1 | `common.py:1080,1098` | Medium (High UX) | **400 ms per approval** |
| 34 | CM-M2 | `common.py:580` | Medium | ~500× fewer ops on diffs |
| 35 | CM-M3 | `common.py:592` | Medium | 5-10× on long diffs |
| 36 | CM-M5 | `common.py:925,949` | Medium | 2-5 ms + thread slot per approval |
| 37 | CFG-M1 | `config.py:893,1136,1544` | Medium | 200μs-1ms per call |
| 38 | CFG-M2 | `config.py:116` | Medium | Maint + ~30μs/write |
| 39 | AT-M1 | `agent_tools.py:315` | Medium | Data-corruption risk |
| 40 | AT-M2 | `agent_tools.py:272` | Medium | ~20μs per call |
| 41 | GM-M1 | `gemini_model.py:57,112` | Medium | 50-200μs per turn |
| 42 | GM-M2 | `gemini_model.py:314` | Medium | 10-100μs per user msg |
| 43 | PS-M1 | `persistence.py:61,82,117` | Medium | 20-100μs per write |
| 44 | CB-M1 | `_core_bridge.py:126-131` | Medium | ~1 ms per 1K-msg batch |
| 45 | CB-M2 | `_core_bridge.py:140` | Medium | Correctness + perf |
| 46 | APP-M1 | `tui/app.py:413-537` | Medium | O(1) vs O(N) dispatch |
| 47 | APP-M2 | `tui/app.py:57,84,90,97` | Medium | Zero queries/keystroke |
| 48 | MB-H2 | `message_bridge.py:315` | Medium | Skip ANSI parser for plain text |
| 49 | SR-M1 | `stream_renderer.py:192` | Medium | 8× fewer allocs in reasoning |
| 50 | COMP-M1 | `completion.py:241` | Medium | scandir vs glob |
| 51 | CR-M1 | `command_runner.py:654,680` | Medium | ~3-5% CPU during shell |
| 52 | CR-M2 | `command_runner.py:144` | Medium | ~80-120μs per 8KB cmd |
| 53 | FO-M1 | `file_operations.py:509` | Medium | ~50-150ms per session |
| 54 | FO-M2 | `file_operations.py:608,630` | Medium | ~20-50μs per read |
| 55 | FO-M3 | `file_operations.py:676,748` | Medium (cold) | 40-100× when triggered |
| 56 | FM-M1 | `file_modifications.py:228+` | Medium | DRY + cache fallback |
| 57 | MEM-CCC-M1 | `claude_cache_client.py:704` | Medium | ~8KB per auth-retry burst |
| 58 | MEM-SS-M1 | `session_storage.py:158` | Medium | Peak RSS during load |
| 59 | MEM-MF-M1 | `model_factory.py:757` | Medium | Correctness + cache alloc |
| 60 | MEM-IL-M1 | `interactive_loop.py:120,493,582` | Medium | DRY + shallow-copy waste |
| 61 | SR-M2 | `stream_renderer.py:67` | Low-Med | ~5-10% attr access |
| 62 | MB-M1 | `message_bridge.py:160-195` | Low-Med | O(1) dispatch |
| 63 | CM-M4 | `common.py:829` | Low-Med | N escapes → 1 per render |
| 64 | CR-M3 | `command_runner.py:196` | Low-Med | micro per command |
| 65 | CR-M4 | `command_runner.py:1280+` | Low-Med | ~2μs × calls |
| 66 | CR-M5 | `command_runner.py:1146+` | Low | Few KB × 5 per command |
| 67 | CR-L1 | `command_runner.py:229` | Low | Dead code removal |
| 68 | CR-L2 | `command_runner.py:~880` | Low-Med | ~10× lock contention |
| 69 | CR-L3 | `command_runner.py:1572` | Low | 2-3× faster spawn |
| 70 | CM-L1 | `common.py:427` | Negligible | Import-time only |
| 71 | CM-L2 | `common.py:1245` | Low | Port + 2× MD5 |
| 72 | FO-M4 | `file_operations.py:428,452` | Low | Single-pass fusion |
| 73 | FO-L1 | `file_operations.py:683` | Low | μs + lint |
| 74 | FM-M2 | `file_modifications.py:239+` | Low | μs + cleanliness |
| 75 | FM-M3 | `file_modifications.py:880,893` | Low | 5-20μs per call |
| 76 | FM-L1 | `file_modifications.py:872` | Low | Lint/correctness |
| 77 | CFG-L1 | `config.py:116` | Low | ~500μs per write |
| 78 | CFG-L2 | `config.py:587` | Low | ~10μs per keystroke |
| 79 | CFG-L3 | `config.py:1031` | Low | ~200ns per call |
| 80 | AT-L1 | `agent_tools.py:218` | Low | ~1μs + consistency |
| 81 | AT-L2 | `agent_tools.py:170,306,366` | Low | ~2μs + DRY |
| 82 | GM-L1 | `gemini_model.py:306,486` | Low | 5-20μs per request |
| 83 | PS-L1 | `persistence.py:148` | Low | 1-5 ms large writes |
| 84 | CB-L1 | `_core_bridge.py:159,163` | Low | 10-100μs per part |
| 85 | APP-L1 | `tui/app.py:415-540` | Low | Maint (folded into APP-M1) |
| 86 | MB-L1 | `message_bridge.py:28` | Low | Correctness only |
| 87 | COMP-L1 | `completion.py:12` | Low | Small memory + attr access |

---

# 🚀 Recommended Implementation Order

## Tier 1 — Ship ASAP (user-visible wins, low risk)
These fixes have the highest ROI and minimal blast radius:

1. **APP-H2** — `asyncio.to_thread(handle_command, ...)` — fixes UI freezes on slash commands
2. **APP-H1** — Cache widget references in `on_mount` — kills per-token DOM queries
3. **SR-H1** — Throttle `_update_rate` to 5 Hz + decouple spinner from rate — **biggest streaming CPU win**
4. **AT-H1** — Wrap session save/load in `asyncio.to_thread` — unblocks parallel sub-agents
5. **FM-H1** — Slice-assign in `_replace_in_file` + preserve line cache — biggest edit-file win
6. **CM-H2** — Prefix-sum line lengths in `_find_best_window` — 10-40× fuzzy match speedup
7. **FO-H1** — Single `os.stat()` per file in `list_files` — 40ms per 1k-file listing
8. **CM-M1** — Remove `asyncio.sleep(0.3) + sleep(0.1)` from approval flow — **400ms × N user wins**

## Tier 2 — Ship in same PR as Tier 1 (compound wins)
9. **SR-H2** — Hoist pydantic_ai imports in stream_renderer
10. **SR-H3** — List-of-fragments text buffer
11. **MB-H1** — Hoist imports + cache `_chat_log` in message_bridge
12. **CFG-H1** — Cache `get_all_model_settings` keyed by model name
13. **CFG-H2** — Delete main-thread token counting from auto_save
14. **PS-H1** — Add async variants to `persistence.py`
15. **COMP-H1** — `os.scandir` + early-exit in file completion
16. **COMP-H2** — `@lru_cache(maxsize=1)` on command/model/agent listings

## Tier 3 — Memory retention fixes (separate PR, stability focus)
17. **MEM-RC-H1** — Cap request_cache bytes or switch to CachedContent model (**biggest RSS win**)
18. **MEM-SS-H1** — Bounded autosave queue + snapshot + atexit shutdown
19. **MEM-ARL-H1** — Lazy `asyncio.Queue` allocation in rate limiter states
20. **MEM-CB-H1** — `weakref.ref(parent)` + Token-based contextvar reset
21. **MEM-CCC-H1** — Hash-keyed JWT cache (perf + security)
22. **MEM-MF-H1** — Hoist `ZaiCerebrasProvider` class

## Tier 4 — Command & File I/O cluster (separate PR)
23. **CR-H1** — `Popen.wait(timeout=)` + parallel kills
24. **CR-H2** — Blocking readline on Windows + stop_event on POSIX
25. **FO-H2** — Cache grep ignore file via `lru_cache(1)` + `atexit`
26. **FO-H3** — Incremental path accumulation
27. **AT-H2** — Delete `_sanitize_messages_for_dbos` or fold into save path
28. **GM-H1** — Cache sanitized tool schemas by `id()`
29. **GM-H2** — Switch SSE parsing to `orjson`
30. **CB-H1** — Hoist ModelRequest import

## Tier 5 — Medium sweep (opportunistic)
All M-ranked findings (#31-60). Good for contributor onboarding. Group by file to minimize PR churn.

## Tier 6 — Low/cleanup sweep
All L-ranked findings (#61-87). Landscaping.

---

# 🔬 Profiling Recipes (Additive to Morning Review's Appendix)

The morning review has profiling recipes for findings H1, H3, H4, M13. Add these for the new High-severity findings:

## Validate SR-H1 (stream_renderer reactive cascade)
```python
# Before/after microbench
import time
from code_puppy.tui.stream_renderer import StreamRenderer

class FakeApp:
    def __init__(self):
        self.query_count = 0
        self.update_count = 0
    def update_token_rate(self, r): self.update_count += 1
    def set_working(self, w, m): self.update_count += 1
    def write_to_chat(self, s): pass

app = FakeApp()
renderer = StreamRenderer(app)
start = time.perf_counter()
# Simulate 10K tokens
for i in range(10000):
    # fake PartDeltaEvent
    ...
elapsed = time.perf_counter() - start
print(f"10K tokens: {elapsed*1000:.1f}ms, updates={app.update_count}")
# Target after fix: update_count ≤ 50 (5 Hz × ~10s worth of tokens)
```

## Validate APP-H2 (sync handle_command blocking)
```bash
# Start the TUI, run a slash command that does I/O, time perceived latency
py-spy record -o slash.svg -- python -m code_puppy --tui
# Type /help, /models, /add_model
# Look for handle_command in the flame graph — should be off-loop after fix
```

## Validate FM-H1 (_replace_in_file triple join)
```python
import timeit
from code_puppy.tools.file_modifications import _replace_in_file_impl

setup = '''
from code_puppy.tools.file_modifications import _replace_in_file_impl
content = "\\n".join(f"line {i}" for i in range(5000))
replacements = [{"old_str": f"line {i*100}", "new_str": f"REPLACED {i}"} for i in range(50)]
'''
t = timeit.timeit("_replace_in_file_impl(content, replacements)", setup=setup, number=10)
print(f"50 replacements × 5K lines × 10 iters: {t:.3f}s")
# Target after fix: 3-10× faster
```

## Validate MEM-RC-H1 (request_cache body retention)
```python
import tracemalloc
import asyncio
from code_puppy.claude_cache_client import ClaudeCacheAsyncClient

tracemalloc.start()
# Fire 256 Claude requests with 75KB bodies
# snapshot = tracemalloc.take_snapshot()
# Target: cache size should not exceed 4MB (with budget fix) or ~20MB (current)
```

## Validate MEM-SS-H1 (autosave closure retention)
```python
import gc, weakref
# 1. Trigger 10 autosaves with a 1000-message history
# 2. Call /clear (replaces history)
# 3. Force gc.collect()
# 4. Check that old history list is freed
# Target: old history should be GC-able after /clear; currently pinned
```

---

# 📐 Methodology Notes

- **Scope**: Static code review only. No runtime profiling performed — appendix recipes are for user validation.
- **Orchestration**: `code-scout` (evidence gathering) → `python-reviewer` × 2 in parallel (3 batches, MAX_PARALLEL_AGENTS=2) → `planning-agent` (synthesis).
- **Deduplication**: All 10 memory-angle findings were cross-referenced against the morning review's 31 findings. Zero overlap. Each finding carries an explicit `Dedup note`.
- **Agents used**: code-scout (1 call), python-reviewer × 3 calls, python-reviewer-clone-1 × 3 calls, planning-agent (synthesis).
- **Coverage gap closed**: Morning review covered 8 of 58 modules (14%). This review adds 14 more modules (24% cumulative). The remaining ~62% of the codebase still has untouched hot paths — notably: `mcp_/`, `browser tools`, `scheduler/`, `agents/base_agent.py`, `messaging/`, `hook_engine/`, `tui/screens/*`.
- **Confidence levels**: High on all findings with concrete line numbers and verified source evidence. Savings estimates are order-of-magnitude, not precise. Every High-severity finding includes enough detail for a reviewer to validate independently.
- **False-positive mitigation**: Every High finding describes BOTH the mechanism AND the expected profile signature. If profiling doesn't match, the finding should be revisited.

---

**Report generated by:** `planning-agent-019d6e` (Plan D Full Sweep)
**Companion document:** `PERFORMANCE_REVIEW_2026-04-08.md` (31 prior findings)
**Combined total:** 118 findings (32 High, 49 Medium, 37 Low) across 22 modules
**Next suggested step:** File bd issues for all Tier 1-3 High-severity findings; run Profiling Recipes for SR-H1 and MEM-RC-H1 before implementing fixes.
