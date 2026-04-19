# bd-186 Phase 6 — Elixir Review

**Reviewer:** elixir-reviewer (OTP / BEAM idiom focus)
**Date:** 2026-04-19
**Scope:** Dual-home config isolation — Phases 2a, 2b, 3, 4 production code
**Verdict:** 🔴 DO NOT CLOSE bd-186 — multiple structural blockers found
**Follow-up issue:** bd-193

---

## Overall assessment

I would not close bd-186 or ship this as-is. The big problem is not ExUnit or OTP mechanics; it's that the core safety boundary still has a few structural holes: `Paths` is resolving homes in an ADR-divergent way, `FirstRun` contains an explicit guard bypass, and the symlink/canonicalization story is not fail-closed yet. The process-dictionary sandbox is actually the least worrying piece here — it's a reasonable BEAM choice for test-local dynamic scope. The routed callsites mostly adopted `Paths.*` cleanly, and the `stderr`/stdio separation thinking is good, but the keystone invariants are not airtight enough for a migration-safety issue.

## Quality-gate baseline

Baseline ran before the review:
- `mix compile --warnings-as-errors` ❌ failed on existing warnings outside review scope
- `mix format --check-formatted` ❌ failed on `doctor.ex` and several tests
- `mix credo --strict` ❌ blocked by existing compile errors
- `mix test` ❌ blocked by same existing compile errors
- `mix dialyzer` ❌ task not configured

Unrelated baseline failures were not treated as bd-186 findings.

## Module status snapshot

| Module | Status | Notes |
|--------|--------|-------|
| `Config.Paths` | 🔴 BLOCKED | Compile-time HOME capture; PUP_HOME/PUPPY_HOME still route Elixir writes |
| `Config.Isolation` | ⚠️ ISSUES | Sandbox solid; guard semantics & symlink defense weaker than ADR |
| `Config.FirstRun` | 🔴 BLOCKED | Explicit raw-write bypass for marker file |
| `Config.Importer` | ⚠️ ISSUES | Reuses Loader (good); symlink handling unsafe; too many responsibilities |
| `Config.Doctor` | ⚠️ ISSUES | Useful checks; false-green on non-IsolationViolation exceptions |
| `Mix.Tasks.PupEx.*` | ✅ PASS w/ caveats | Thin wrappers fine, discoverable |
| Routed callsites | ✅ PASS (spot-check) | ModelPacks/Registry/Policy/Skills/UC refactor clean |
| Tests | ⚠️ ISSUES | Good env/async discipline; some ADR-divergent assertions; edge cases missing |

## Findings by severity

### 🔴 BLOCKER — paths.ex:39, 66, 80, 349 — compile-time HOME capture

`@home_dir Path.expand("~")` freezes HOME at compile time, not runtime. A release built on machine X and run on machine Y has `home_dir/0` and `legacy_home_dir/0` pointing at X's home.

**Fix:** Replace `@home_dir` with a runtime helper. Keep only true constants in module attributes.

**🐍 Python-ism detected:** treating a module attribute like runtime configuration.

### 🔴 BLOCKER — paths.ex:53-63, 330-358, 307-313 — PUP_HOME/PUPPY_HOME still used as Elixir fallbacks

ADR-003 explicitly says these remain Python-scoped. Current code still routes Elixir home resolution through them. `ensure_dirs!/0` then mutates resolved paths via raw `File.mkdir_p!` — so `PUP_HOME=~/.code_puppy` makes Elixir create directories in the legacy tree.

**Fix:** Ignore `PUP_HOME`/`PUPPY_HOME` for Elixir path resolution. Emit one-time deprecation warning on detection. Route directory creation through `Isolation.safe_mkdir_p!/1`.

### 🔴 BLOCKER — first_run.ex:118-124 — explicit guard bypass

`write_initialized_marker/0` rescues guard failure and falls back to raw `File.write/2`. Comment says "not security-critical" but ADR does not allow "warning-level bypass" exceptions.

**Fix:** Remove the raw `File.write/2` fallback. Return `{:error, reason}` or log warning and leave the marker absent.

### 🟠 HIGH — paths.ex + isolation.ex — symlink defense not fail-closed

1. `canonical_resolve/1` silently returns partially-resolved path on depth cap (paths.ex:243-245, 295-299)
2. `in_legacy_home?/1` canonicalizes candidate but not legacy root (isolation.ex:166-176) — root-symlink bypass
3. Check-then-call pattern in safe wrappers is TOCTOU-vulnerable (isolation.ex:46-78)

**Fix:** Canonicalize both sides. Fail-closed on over-depth. Revalidate around actual mutation.

### 🟠 HIGH — isolation.ex:121-139 — guard allows any non-legacy path

ADR-003 says safe wrappers validate target is UNDER the Elixir home. Current `allowed?/1` is "not sandboxed AND not legacy → allow" — so `/tmp/...` and arbitrary absolute paths all succeed.

**Fix:** Default policy becomes "under canonical Elixir home, or explicit sanctioned exception".

### 🟠 HIGH — importer.ex:71-76, 162-185, 420-460 — symlink escape + unbounded recursion

`walk_dir/2` uses `File.dir?/1`/`File.regular?/1` which follow symlinks. `read_from_legacy/1` falls back to raw `File.read/1` whenever resolved path is no longer "in legacy home" — allows arbitrary file reads outside the legacy tree. Symlink loops can recurse indefinitely.

**Fix:** Use `File.lstat/1` or `:file.read_link_info`. Require canonical source to stay under canonical legacy root. Add cycle detection.

### 🟡 MEDIUM — paths.ex:362-369 — non-atomic "warn once"

`:persistent_term.get` + `:persistent_term.put` is not atomic. Concurrent startup can double-log.

**Fix:** ETS `insert_new/2` on named table, or serialize through dedicated process.

### 🟡 MEDIUM — isolation.ex:75-78 — safe_rm_rf!/1 bang/spec mismatch

Spec says `{:ok, files} | {:error, reason, path}`. Implementation calls non-bang `File.rm_rf/1`. Bang name but non-bang semantics.

**Fix:** Rename to `safe_rm_rf/1` OR switch to `File.rm_rf!/1` with raising contract.

### 🟡 MEDIUM — doctor.ex:124-130 — false-green on unexpected exceptions

Only `IsolationViolation` proves the guard worked. Other exceptions currently pass.

**Fix:** Only `IsolationViolation` = pass. All other exceptions = fail.

### 🟢 LOW — isolation.ex:181-186 vs telemetry.ex:105-216 — telemetry namespace split

Isolation uses `[:code_puppy_control, :config, :isolation_violation]`. Rest of app uses `[:code_puppy, ...]`. `process: self()` adds PID/cardinality noise.

**Fix:** Document split as intentional OR expose through shared helper. Consider dropping PID metadata.

## Per-focus-area verdicts

1. `with_sandbox/2` process-dict usage — Pass with caveat (idiomatic for test-local dynamic scope)
2. Canonical path resolution — Concern (not fail-closed; root not canonicalized; TOCTOU)
3. Telemetry — Mixed (namespace diverges from app convention; synchronous emission)
4. Deprecation warning — Concern (racey once-guard; Python vars shouldn't be Elixir fallbacks at all)
5. Importer size (515 lines) — Concern (natural split available; reuses Loader)
6. `safe_rm_rf!/1` return type — Concern (bang/non-bang mismatch)
7. First-run stderr — Mostly pass with caveats
8. Doctor safety — Concern (false-green on unexpected exceptions)
9. Mix task structure — Pass
10. Test sandbox patterns — Mostly pass; missing exception/symlink/concurrency cases

## Positive observations

- `with_sandbox/2` well-structured: correct try/after cleanup, correct nested restoration
- Process-local dynamic scope is the right abstraction for this sandbox
- Path refactor is real, not cosmetic — hardcoded paths replaced throughout
- Importer reuses `Config.Loader` for INI parsing (avoids drift)
- First-run banner to stderr is thoughtful for stdio-service compatibility
- OTP hygiene on routed GenServers is decent

## ADR divergences

Clear divergences:
- Home resolution: ADR says PUP_EX_HOME → XDG → ~/.code_puppy_ex. Implementation still uses PUP_HOME/PUPPY_HOME as real fallbacks.
- Guard semantics: ADR says "must be under Elixir home". Implementation is "not legacy".
- No-bypass claim: ADR forbids bypass. `ensure_dirs!/0` and `write_initialized_marker/0` both bypass.
- Symlink defense: ADR claims canonical resolution. Root-symlink, over-depth, TOCTOU not covered.
- First-run activation: No call to `FirstRun.initialize/0` in production (not wired into application.ex).
- XDG semantics: ADR says "within Elixir home tree". Implementation uses external XDG_* directly.

Places matching ADR well:
- Telemetry event name literal match
- Importer is opt-in only
- Allowlist shape + Loader reuse
- Mix task naming

## Test coverage gaps

1. `with_sandbox/2` cleanup when `fun` raises
2. Concurrent deprecation warnings
3. Legacy home root itself is a symlink
4. Importer symlink escape / symlink loop
5. Fail-closed behavior on excessive symlink depth
6. TOCTOU late-symlink swap around `safe_write!/2`
7. ADR-correct env-var behavior (paths_test.exs:53-58, 109-115 currently assert the wrong contract)
8. First-run concurrency (two concurrent `initialize/0` calls)
