# bd-186 Phase 6 — Security Audit

**Reviewer:** security-auditor (attack surface focus)
**Date:** 2026-04-19
**Scope:** Dual-home config isolation — production code + Mix tasks
**Methodology:** File review + live reproduction of identified bypasses
**Verdict:** 🔴 RELEASE BLOCKER
**Follow-up issue:** bd-193

---

## Executive summary

**Overall risk: High — release blocker.**

If this ships as-is, the core safety invariant is NOT structurally guaranteed. Under realistic conditions — inherited `PUP_HOME`, precompiled release built under a different HOME, or a symlinked legacy home — Elixir pup-ex can still write into the Python pup's `~/.code_puppy/`. Separately, the importer can copy **forbidden credential files** and **arbitrary symlinked external files** into `~/.code_puppy_ex/`, while `mix pup_ex.doctor` can still report success in broken states.

The single most critical issue is that legacy-home detection is based on a **compile-time, non-canonical root** and is undermined further by **raw `File.*` bypasses** in first-run setup.

**Compliance posture:** falls short of ADR-003 and OWASP ASVS Level 2 expectations for trust-boundary enforcement, secure file/config handling, sensitive-data isolation, and fail-safe diagnostics.

## Reproduction evidence

All reproductions used isolated temp directories, NOT the real user home:

- **Compile-time HOME capture confirmed:** compiling `paths.ex` under temp HOME A and running under temp HOME B returned HOME A for both `legacy_home_dir/0` and `home_dir/0`.
- **Legacy-root symlink bypass confirmed:** with `.code_puppy` symlinked to another temp dir, `Isolation.safe_write!()` created `pwned.txt` in the real target.
- **`PUP_HOME` fallback writes confirmed:** `FirstRun.initialize()` with only `PUP_HOME` set created `.initialized` under that `.code_puppy` path.
- **Forbidden skill secret copy confirmed:** `Importer.run(confirm: true, ...)` copied `skills/evilskill/oauth_token_backup.json` while also listing it under `refused`.
- **Symlink escape confirmed:** `agents/steal.json -> outside_secret.txt` imported and copied outside file contents.

## Findings by severity

### 🔴 CRITICAL — Legacy-home detection stale + non-canonical → direct guard bypass

**Files:** `paths.ex:39,79-80,238-299`, `isolation.ex:166-176`

**Attack:** Burrito/release compiled on X, run on Y — OR local adversary symlinks `~/.code_puppy`. `legacy_home_dir/0` baked from `@home_dir Path.expand("~")` at compile time. `in_legacy_home?/1` canonicalizes only candidate, not legacy root. Writes to real Python home misclassified as "not legacy" and allowed.

Also gaps: macOS `/var` → `/private/var` mismatch; `Path.expand/1` lexical `..` collapse before symlink walking; symlink-depth exhaustion returns partial path.

**Impact:** Direct breach of primary invariant. Elixir writes into Python pup. Live state corruption.

**Mitigation:** Runtime roots on both sides. Canonicalize both. Fail closed on loops/depth/ambiguity. Regression tests for compile-home ≠ runtime-home, root-symlink, `/var`, `symlink/../target`.

### 🔴 CRITICAL — Elixir honors Python env vars + first-run uses raw `File.*`

**Files:** `paths.ex:52-67,307-313,330-358`, `first_run.ex:78-125`

**Attack:** User has `PUP_HOME=~/.code_puppy` for Python. Elixir starts. `Paths.home_dir/0` + `xdg_dir/1` honor that. `FirstRun.initialize/0` calls `Paths.ensure_dirs!/0` (raw `File.mkdir_p!`). Then `write_initialized_marker/0` rescues safe_write failure → raw `File.write/2`.

Confirmed: with only `PUP_HOME` set, `FirstRun.initialize()` created `.initialized` under `.code_puppy`. With `PUP_EX_HOME=$HOME/.code_puppy/newhome`, initialization created `.initialized` inside the legacy subtree.

**Impact:** Concrete legacy-home write path. Defeats "never write to Python pup". Realistic accidental damage.

**Mitigation:** Remove PUP_HOME/PUPPY_HOME as Elixir fallbacks. Validate PUP_EX_HOME + XDG against canonical legacy root. Replace raw File.* with guard-enforced ops only.

### 🔴 CRITICAL — Importer copies forbidden credentials inside skills/

**Files:** `importer.ex:150-159, 298-313, 404-456`

**Attack:** Adversary plants `~/.code_puppy/skills/evilskill/SKILL.md` + `~/.code_puppy/skills/evilskill/oauth_token_backup.json`. User runs `mix pup_ex.import --confirm`. Scan records refused; `copy_directory_tree/4` copies entire skill directory recursively.

Reproduced: `oauth_token_backup.json` in BOTH `refused` AND `copied`.

**Impact:** Explicit credential leakage path. Violates ADR forbidden-import rules.

**Mitigation:** Re-apply deny/allow per file on recursion. Expand forbidden filename coverage (API keys, cookies, etc.).

### 🟠 HIGH — Importer symlink escape, arbitrary file copy

**Files:** `importer.ex:71-76, 162-185, 364-391, 420-456`

**Attack:** `~/.code_puppy/agents/steal.json -> /etc/passwd` or symlinked subdir in skill tree. `File.dir?/1`/`File.regular?/1` follow symlinks. `read_from_legacy/1` falls back to raw `File.read/1` when `in_legacy_home?/1` returns false.

Reproduced: outside file contents copied into destination tree.

**Impact:** Arbitrary local file disclosure. Traversal + DoS.

**Mitigation:** `File.lstat` / `:file.read_link_info` — reject symlinks. Canonical source-under-canonical-legacy check before each read.

### 🟠 HIGH — safe_* wrappers don't enforce "inside Elixir home" + TOCTOU

**Files:** `isolation.ex:45-79,121-139,166-176`, `paths.ex:295-299`

**Attack:** Developer/plugin passes `/tmp/outside.txt`. `allowed?/1` is "true unless legacy" → write succeeds.

Reproduced. Also check-then-act is TOCTOU-vulnerable.

**Impact:** Guard not structurally enforcing ADR. Race-based redirection.

**Mitigation:** Policy becomes "must be under canonical Elixir home". Reject symlinked parents. Document residual TOCTOU risk if atomic no-follow unavailable.

### 🟠 HIGH — Doctor can falsely report "isolated" when guard broken

**Files:** `doctor.ex:99-130`

`check_isolation_guard/0` treats ANY non-`IsolationViolation` exception as success. Probe filename deterministic. Cleanup uses raw `File.rm`.

**Impact:** CI/release/user self-checks can report healthy isolation when guard is compromised.

**Mitigation:** Pass ONLY on `IsolationViolation`. All other exceptions = fail. Randomize probe name.

### 🟡 MEDIUM — Importer has no size/count/recursion limits

**Files:** `importer.ex:71-76, 197-210, 237-264, 404-456`

**Attack:** Hostile tree with huge `models.json`, massive `puppy.cfg`, deeply nested skills. Eager reads, JSON decode, recursive copy without budgets.

**Impact:** Memory exhaustion, CPU spikes, local DoS.

**Mitigation:** `File.stat` caps before opening. Byte/file-count/depth budgets. Keep "legacy read path only" strict.

### 🟡 MEDIUM — Mix tasks + importer swallow security-relevant failures

**Files:** `mix/tasks/pup_ex/import.ex:42-97`, `mix/tasks/pup_ex/auth/login.ex:43-57`, `importer.ex:465-473`

Tasks print messages but don't enforce non-zero exit on isolation errors. `Importer.maybe_write/3` rescues all exceptions into generic `{:error, message}`.

**Impact:** CI guardrails misread broken migration as success.

**Mitigation:** Non-zero exit when errors != []. Preserve isolation violations as first-class failures.

### 🟢 LOW — Path, filename, PID leakage in console + telemetry

**Files:** `isolation.ex:181-186`, `doctor.ex:75-77,114-115,175-177`, `mix/tasks/pup_ex/import.ex:53-90`, `mix/tasks/pup_ex/auth/login.ex:47-56`, `paths.ex:368-370`

Absolute home paths, filenames like `oauth_token_backup.json`, probe locations, PIDs in telemetry leak into CI logs / support transcripts. NO import content logging observed (good).

**Mitigation:** Redact home prefixes. Don't print forbidden filenames unless debug. Drop `process: self()` from default telemetry.

## Per-focus-area verdict

| Area | Verdict |
|------|---------|
| A. Path resolution attack vectors | **FAIL** |
| B. Env var injection | **FAIL** |
| C. Importer trust boundary | **FAIL** |
| D. Credential / secret leakage | **FAIL** |
| E. Guard escape hatches | **FAIL** |
| F. Telemetry / logging | **CONCERN** |
| G. Mix task argument handling | **CONCERN** |

## ADR-003 claim audit

### Claim: "cannot accidentally damage Python pup"

**Verdict: structurally false today.**

- PUP_HOME/PUPPY_HOME accepted as Elixir write roots
- ensure_dirs!/0 raw File.mkdir_p!
- write_initialized_marker/0 raw File.write/2 fallback
- legacy_home_dir/0 compile-time and non-canonical
- Root-symlink / canonicalization mismatches

### Claim: "guard is always active, no config flag to disable"

**Verdict: not structurally true in practice.**

No explicit config flag, but effective bypasses:
- Direct raw File.* mutations
- Rescue fallback after guard failure
- safe_* wrappers enforce "not legacy", not "inside Elixir home"
- with_sandbox/2 is an in-process bypass (test-intended)

### ADR gate readout

| Gate | Auto test | Structurally trustworthy? |
|------|-----------|---------------------------|
| GATE-1 No-write | ✅ passes | ⚠️ Not — bypasses exist |
| GATE-2 Guard raises | ✅ passes | ⚠️ Simple cases only |
| GATE-3 Import opt-in | ✅ passes | ✅ Actually true |
| GATE-4 Doctor passes | ✅ passes | ⚠️ Not — false greens |
| GATE-5 Paths audit | ✅ passes | ⚠️ Not met in spirit |

## Must-fix (blocks bd-186 close, tracked in bd-193)

1. Runtime-canonical home/legacy resolution. No `@home_dir`. Ignore PUP_HOME/PUPPY_HOME. Canonicalize both. Fail closed.
2. Guard enforces "must be under canonical Elixir home + not canonical legacy". Reject symlinked parents.
3. Remove every raw `File.*` escape: `Paths.ensure_dirs!/0`, `FirstRun.write_initialized_marker/0`, rescue-then-write branches.
4. Importer: deny/allow per-file on recursion. Reject symlinks via lstat. Canonical source-under-canonical-legacy. Byte/count/depth caps.
5. Doctor: pass only on IsolationViolation. All other exceptions = fail.

## Follow-up (OK after blockers)

1. Non-zero exit on security errors in mix tasks
2. Reduce path/filename/PID leakage
3. Semgrep/CI grep banning raw File.* in config/isolation modules
4. Release-mode regression tests for compile-home ≠ runtime-home

## Verification before re-approval

- Release-style test: compile HOME A, run HOME B
- Symlinked `~/.code_puppy` root test
- Symlinked subtree test
- PUP_HOME/PUPPY_HOME ignored-by-Elixir
- PUP_EX_HOME inside legacy rejected hard
- Forbidden nested skill file never copied
- Symlinked agent/skill file rejected
- Doctor non-zero on all unexpected exceptions
- No-write gate: zero bytes written under legacy home

**Success metric:** All ADR-003 gates structurally trustworthy. Zero direct `File.*` mutations in reviewed config modules outside approved wrappers.

## Positive controls observed

- `mix pup_ex.import` is opt-in, defaults to dry-run
- Importer attempts default-deny allowlist
- Mix task argument handling straightforward; no shell injection
- `mix pup_ex.auth.login` uses isolation wrappers
- Isolation telemetry exists (right idea once guard is fixed)

## Overlap with elixir-reviewer

Expected overlap: compile-time HOME capture, raw `File.*` bypasses, symlink/canonicalization weakness, broad rescue, doctor false-pass, TOCTOU.

Security-specific additions (dynamically confirmed):
- Forbidden credential files inside `skills/` still copied
- Symlink exfiltration via importer
- `safe_write!` reaches symlinked legacy target
- PUP_HOME/PUP_EX_HOME combinations produce real writes in legacy-shaped paths
