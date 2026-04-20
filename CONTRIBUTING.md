# Contributing to Code Puppy

**Thank you for your interest in contributing!** This document outlines the guidelines for participating in this project.

## 🧊 Python Freeze Policy (during Elixir migration)

> **TL;DR**: The Python codebase is **FROZEN** during the Python→Elixir migration (bd-132 epic). 
> Only critical bug fixes, deprecation warnings, and docs updates are allowed.

### Rationale

Code Puppy is actively migrating from Python to Elixir (the `pup-ex` rewrite). During this transition:
- The Elixir codebase (`elixir/code_puppy_control/`) is where **new development happens** 
- The Python codebase (`code_puppy/`) is in **maintenance mode only** 
- Dual-maintenance would fragment effort and delay the migration

### What's Allowed ✅

| Type | Examples |
|----------|----------|
|**_Critical bug fixes_** | Crashes, data loss, security vulnerabilities |
|**_Deprecation warnings_** | Guiding users toward `pup-ex` equivalents |
|**_Documentation updates_** | README fixes, migration guides, API docs |
|**_CI/infrastructure_** | Changes that don't touch `code_puppy/**/*.py` |

### What's NOT Allowed ❌

| Type | Examples |
|----------|-----------|
|**_Refactors_** | Code reorganization, style changes, renaming |
|**_Schema changes_** | `puppy.cfg` modifications, `*.json` config changes |
|**_New features_** | New commands, tools, agents, or capabilities |
|**_Non-critical fixes_** | Typos, cosmetic bugs, edge cases with workarounds |

### What Reviewers Should Enforce

1. **Check the file path** - If it touches `code_puppy/**/*.py`, scrutinize heavily
2. **Require justification** - Every Python change needs a bd issue reference
3. **Label appropriately** - Use `bug-fix`, `docs`, or `deprecation` labels
4. **Ask: "Could this go in Elixir?"** - If yes, redirect the contributor

### Emergency Override Process

If a critical production fix is needed:
1. File a bd issue with label `critical-freeze-override`
2. Get approval from a maintainer
3. Merge with the appropriate conventional commit type (`fix` for bug fixes, `docs` for documentation) with `bd-187` referenced in the body
4. Create a follow-up issue to port the fix to Elixir

### Timeline

This freeze remains in effect until the Elixir migration reaches parity (tracked in bd-132). The freeze will be lifted incrementally as components are fully migrated.

---

## General Development Guidelines

### Branch Naming
- `feature/bd-XXX-description` for new features
- `fix/bd-XXX-description` for bug fixes
- `docs/bd-XXX-description` for documentation

### Commit Format

We use conventional commits with bd issue references:

```
type(bd-XXX): Brief description

Longer explanation if needed.

```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Code Review

All changes require review. The Python freeze policy (above) will be strictly enforced during the migration period.

Note: the `python-freeze-check.yml` workflow posts advisory warnings only; enforcement is reviewer-driven.

### Testing

- Add tests for bug fixes
- Ensure existing tests pass
- For Elixir code, run `mix test` in `elixir/code_puppy_control/`

### Questions?

> Reach out via:
> - bd issues for feature requests and bugs
- Pack Leader agents for architectural questions

## Testing Tiers

During development, use tiered testing to minimize feedback time while maintaining quality.

### Test Commands by Context

| Context | Command | Scope |
|---------|---------|-------|
| Active development | `mix test.changed` | Changed files + their tests |
| Before commit | `mix test.changed --depth 2` | + dependent modules |
| Closing a bd issue | `mix test` | Full unit suite |
| Closing an epic | `mix test && mix test --only integration` | Everything |
| CI pipeline | Full suite | Always runs everything |

### Escalation Triggers

Always run the **full test suite** (`mix test`) when:

- **Config files changed:** `config/*.exs`, `mix.exs`
- **Test infrastructure changed:** `test/support/*`, `test_helper.exs`
- **Database migrations added/modified:** `priv/repo/migrations/*`
- **Many files changed:** 10+ files in a single change
- **Cross-cutting modules touched:** `application.ex`, `telemetry.ex`, `repo.ex`

### Quick Reference

```bash
# Development (fast)
mix test.changed              # Tests for uncommitted changes
mix test.changed --staged     # Tests for staged changes only
mix test.changed --base main  # Tests since branching from main

# Deeper analysis
mix test.changed --depth 2    # Include tests for dependent modules

# Full validation
mix test                      # All unit tests
mix test --only integration   # Integration tests
mix test --only e2e           # End-to-end tests
```

**Rule:** Agents default to `mix test.changed` during development. Full suite runs on issue/epic close.
