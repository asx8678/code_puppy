# Phase 4.2 - Dependency & Configuration Audit Findings

**Project:** code_puppy  
**Audit Date:** 2026-04-07  
**Audited Files:**
- `pyproject.toml`
- `uv.lock` (reviewed, clean)
- `.env.example`
- `lefthook.yml`
- `Cargo.toml` (workspace and crate manifests)
- `coverage.json`

## Summary
| Severity | Count |
|----------|-------|
| MEDIUM   | 4     |
| LOW      | 9     |
| INFO     | 3     |
| **Total**| **16**|

---

## [SEV-MEDIUM] Hardcoded ripgrep Version Pin Without Auto-Update Policy
**File:** pyproject.toml:29
**Issue:** The `ripgrep==15.0.0` package is pinned to an exact version. This Python package wraps the ripgrep binary and may need updates for security patches. The project depends on ripgrep for file operations and search functionality, but there's no documented policy for tracking upstream ripgrep CVEs or updating this wrapper package.
**Fix:** 
1. Document a process for monitoring ripgrep security releases
2. Consider using `>=` constraint with known-safe minimum version
3. Add CI check to flag when ripgrep wrapper is >3 months old

---

## [SEV-MEDIUM] Low Coverage Threshold May Hide Risk Areas
**File:** pyproject.toml:96
**Issue:** `fail_under = 65` sets a relatively low coverage floor. Security-critical code paths (auth, token handling, file operations) should have higher coverage. The current threshold may allow untested security-sensitive code to pass CI.
**Fix:** 
1. Raise `fail_under` to at least 80% for production code
2. Use `exclude_lines` pragma to mark intentionally uncovered defensive code
3. Consider separate coverage thresholds for security-critical modules vs UI code

---

## [SEV-MEDIUM] Coverage Exclusion for Entry Point Code
**File:** pyproject.toml:93
**Issue:** `omit = ["code_puppy/main.py"]` excludes the entry point from coverage. Entry points often handle initialization, signal handling, and error paths that are critical for security. The comment in main.py indicates it delegates to cli_runner, but the delegation itself isn't tested.
**Fix:** 
1. Remove the omit or add specific `# pragma: no cover` comments to justified exclusions
2. Test the import and delegation behavior in integration tests
3. Document why this file is excluded

---

## [SEV-MEDIUM] .env File Loading Uses override=True
**File:** code_puppy/config.py:1803
**Issue:** The `load_dotenv(env_file, override=True)` call means .env values take precedence over existing environment variables. This could allow a malicious .env file in a shared project directory to override system-level security settings or API keys.
**Fix:** 
1. Change to `override=False` so system env vars take precedence
2. Or add a security warning when override=True is in effect
3. Document this behavior in .env.example with a security note

---

## [SEV-LOW] .env.example Missing git-commit Warning
**File:** .env.example:1
**Issue:** The .env.example file has a comment noting `.env` takes priority over `~/.code_puppy/puppy.cfg`, but lacks prominent warnings about:
1. Risks of committing .env files to git
2. Where .env files should/shouldn't be placed
**Fix:** 
1. Add header comment: "⚠️ SECURITY: Never commit this file with real keys to git"
2. Add note about override behavior (already partially documented)
3. Reference SECURITY.md for key management best practices

---

## [SEV-LOW] Anthropic Package Pinned Without Upper Bound
**File:** pyproject.toml:37
**Issue:** `anthropic==0.79.0` is pinned exactly. While this prevents unexpected breaking changes, it also means security fixes in the Anthropic SDK won't be picked up automatically. The security audit previously found this same pattern.
**Fix:** 
1. Use constraint like `anthropic>=0.79.0,<1.0.0` after testing
2. Add Dependabot or similar to flag security updates
3. Document the testing procedure for SDK updates

---

## [SEV-LOW] pydantic-ai-slim Pinned to Exact Version
**File:** pyproject.toml:15
**Issue:** `pydantic-ai-slim[openai,anthropic,mcp]==1.60.0` is pinned exactly. This is a core framework dependency with security implications (handles API calls, authentication, etc.).
**Fix:** 
1. Document policy for reviewing and updating pinned core dependencies
2. Consider `>=` constraint with manual security review process
3. Add CI check that flags when pinned deps are >30 days old

---

## [SEV-LOW] coverage.json Committed to Repository
**File:** coverage.json (1.6MB in repo root)
**Issue:** The coverage.json file (1.6MB) is committed to the repository. `.gitignore` only contains `.coverage`; `coverage.json` is missing from `.gitignore` and should be added. This generated data causes repository bloat, can leak information about code structure through coverage gaps, and may become stale relative to actual code.
**Fix:** 
1. Add `coverage.json` to `.gitignore`
2. Remove from repository with `git rm --cached`
3. Generate fresh in CI if needed for reporting

---

## [SEV-LOW] Rust Crate Dependencies Not Pinned in Cargo.lock at Crate Level
**File:** turbo_parse/Cargo.toml:36-47
**Issue:** Dependencies like `tree-sitter = "0.24"`, `lru = "0.12"`, `rayon = "1.10"` use loose version constraints. `Cargo.lock` exists at the workspace root (appropriate for a workspace), but without strict constraints in the crate manifest, builds may pull different versions over time, potentially including breaking changes or vulnerable crates.
**Fix:** 
1. Use stricter constraints like `= "0.24.0"` for security-critical crates, OR
2. Document the policy for updating Rust dependencies and verify workspace-level Cargo.lock is sufficient
3. Ensure CI uses `--locked` flag for cargo builds

---

## [SEV-LOW] libloading Feature Flag in turbo_parse
**File:** turbo_parse/Cargo.toml:50
**Issue:** The `libloading` crate (optional, for dynamic-grammars feature) enables loading shared libraries at runtime. While currently optional, if enabled it could be a security vector for loading untrusted code.
**Fix:** 
1. Document security implications of the dynamic-grammars feature
2. Add runtime validation if dynamic library loading is ever enabled
3. Consider requiring explicit opt-in for this feature in production

---

## [SEV-LOW] Dev Dependencies May Include Production-Useful Tools
**File:** pyproject.toml:98-107
**Issue:** `maturin`, `ruff`, `pexpect` are in `dev` group but may be used in ways that affect runtime:
- maturin is used for building Rust extensions - may be needed for source installs
- pexpect is used in some integration test scenarios
**Fix:** 
1. Verify all `dev` group deps are truly dev-only
2. Move any runtime-critical tools to main dependencies or document why they're dev-only
3. Consider a `build` dependency group for maturin

---

## [SEV-LOW] lefthook Scripts Use Command -v Pattern
**File:** lefthook.yml:7-41
**Issue:** The lefthook pre-commit scripts use `command -v` to detect tools. While not a direct security issue, this pattern could be confused with malicious PATH manipulation if audit trails are reviewed.
**Fix:** 
1. Document the `command -v` usage in a comment
2. Consider using full paths for security-critical linting tools
3. Add a note about lefthook in SECURITY.md for security reviewers

---

## [SEV-LOW] Missing Environment Variable Validation at Startup
**File:** code_puppy/config.py:1800-1815
**Issue:** The `load_env_file_and_config()` function loads API keys from multiple sources (.env, puppy.cfg) but doesn't validate:
1. Whether keys appear valid (format check)
2. Whether keys have suspicious patterns (common test keys)
3. Whether multiple conflicting keys exist
**Fix:** 
1. Add basic format validation for API keys at startup (warn on obviously invalid formats)
2. Log warnings if keys are loaded from multiple sources (env vs .env vs config)
3. Add a `/config validate` command to check key validity without exposing values

---

## [INFO] Version Pinning Strategy is Documented
**File:** pyproject.toml:12-16
**Note:** The dependency section has a good comment explaining the pinning strategy: "Minimum version constraints. Exact versions are pinned in uv.lock. CI MUST use `uv sync --frozen` to enforce the lockfile." This is good security practice.

---

## [INFO] PyO3 Version Uses Workspace Dependencies
**File:** Cargo.toml:6, turbo_parse/Cargo.toml, code_puppy_core/Cargo.toml
**Note:** PyO3 is version-pinned at workspace level (`pyo3 = { version = "0.28", ... }`), which is good for consistency. No immediate security concern, but maintain awareness of PyO3 security advisories.

---

## [INFO] License Consistency
**File:** pyproject.toml:43, turbo_parse/Cargo.toml:6, turbo_ops/Cargo.toml:6
**Note:** Project uses MIT license consistently across Python and Rust components. No unusual licenses detected in direct dependencies.

---

## Recommendations Summary

### High Priority
- [ ] Review and update coverage threshold policy
- [ ] Add security warnings to .env.example
- [ ] Consider override=False for dotenv loading

### Medium Priority
- [ ] Document dependency update policy for pinned packages
- [ ] Remove coverage.json from repository
- [ ] Add environment variable validation at startup
- [ ] Verify workspace-level Cargo.lock is sufficient for reproducible builds

### Low Priority
- [ ] Audit tree-sitter and pyo3 dependencies for known CVEs
- [ ] Document libloading security implications
- [ ] Review lefthook script documentation

---

*Audit conducted as Phase 4.2 of Security Review. No web search available; manual CVE checking recommended for flagged dependencies.*
